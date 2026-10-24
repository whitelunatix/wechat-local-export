#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export WeChat 4.x message tables to JSONL or CSV.

The input must be an already-decrypted SQLite database. This script discovers
message tables dynamically and never derives or extracts encryption keys.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

WANTED_COLUMNS = [
    "create_time",
    "local_id",
    "sender_username",
    "message_content",
    "type",
    "is_sender",
    "server_id",
    "sort_seq",
]
OUTPUT_FIELDS = ["session", "create_time", "datetime", "local_id", "sender", "type", "content"]
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def load_name_map(con: sqlite3.Connection) -> dict[str, str]:
    """Return md5(user_name) -> user_name when a Name2Id table is available."""
    try:
        rows = con.execute("SELECT rowid, user_name FROM Name2Id").fetchall()
    except sqlite3.Error:
        return {}
    mapping: dict[str, str] = {}
    for _rowid, name in rows:
        if not name:
            continue
        digest = hashlib.md5(str(name).encode("utf-8")).hexdigest().lower()
        mapping[digest] = str(name)
    return mapping


def message_tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'Msg_%' COLLATE NOCASE ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def columns_of(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f"PRAGMA table_info({quote_identifier(table)})")]


def decode_content(value: Any, decompress: bool) -> Any:
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        if decompress and value.startswith(ZSTD_MAGIC):
            try:
                import zstandard

                value = zstandard.ZstdDecompressor().decompress(value)
            except Exception:
                pass
        return value.decode("utf-8", errors="replace")
    return value


def iter_rows(
    con: sqlite3.Connection,
    table: str,
    columns: list[str],
    since_ts: int | None,
    limit: int | None,
    decompress: bool,
) -> Iterable[dict[str, Any]]:
    selected = [column for column in WANTED_COLUMNS if column in columns]
    if "message_content" not in selected:
        return
    sql = f"SELECT {', '.join(quote_identifier(c) for c in selected)} FROM {quote_identifier(table)}"
    params: list[Any] = []
    if since_ts is not None and "create_time" in selected:
        sql += " WHERE create_time >= ?"
        params.append(since_ts)
    order = [c for c in ("create_time", "local_id") if c in selected]
    if order:
        sql += " ORDER BY " + ", ".join(quote_identifier(c) for c in order)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    cursor = con.execute(sql, params)
    for row in cursor:
        record = dict(zip(selected, row))
        create_time = record.get("create_time")
        try:
            dt = datetime.fromtimestamp(int(create_time)).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            dt = ""
        yield {
            "create_time": create_time,
            "datetime": dt,
            "local_id": record.get("local_id"),
            "sender": record.get("sender_username") or record.get("is_sender"),
            "type": record.get("type"),
            "content": decode_content(record.get("message_content"), decompress),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export decrypted WeChat 4.x messages.")
    parser.add_argument("--db", required=True, help="Path to message_*.decrypted.db")
    parser.add_argument("--out", required=True, help="Output .jsonl or .csv file")
    parser.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    parser.add_argument("--session", help="Only export this user_name")
    parser.add_argument("--since", help="Start date, YYYY-MM-DD (local time)")
    parser.add_argument("--limit", type=int, help="Maximum number of messages to export")
    parser.add_argument("--decompress", action="store_true", help="Try zstd-decompressing message_content")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        parser.error(f"database not found: {db_path}")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    since_ts = None
    if args.since:
        try:
            since_ts = int(datetime.strptime(args.since, "%Y-%m-%d").timestamp())
        except ValueError:
            parser.error("--since must be YYYY-MM-DD")

    con = connect_readonly(db_path)
    try:
        name_map = load_name_map(con)
        tables = message_tables(con)
        if args.session:
            target = args.session.lower()
            filtered = []
            for table in tables:
                suffix = table[4:].lower()
                if suffix == target or name_map.get(suffix, "").lower() == target:
                    filtered.append(table)
            tables = filtered
        if not tables:
            print("no matching Msg_* tables", file=sys.stderr)
            return 1

        written = 0
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = None
            if args.format == "csv":
                writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
                writer.writeheader()

            for table in tables:
                if args.limit is not None and written >= args.limit:
                    break
                suffix = table[4:].lower()
                session = name_map.get(suffix, table)
                remaining = None if args.limit is None else args.limit - written
                columns = columns_of(con, table)
                for record in iter_rows(con, table, columns, since_ts, remaining, args.decompress):
                    record["session"] = session
                    ordered = {field: record.get(field) for field in OUTPUT_FIELDS}
                    if writer is not None:
                        writer.writerow(ordered)
                    else:
                        handle.write(json.dumps(ordered, ensure_ascii=False) + "\n")
                    written += 1
                    if args.limit is not None and written >= args.limit:
                        break
                print(f"  {table}: exported (total {written})", file=sys.stderr)

        print(f"done: {written} message(s) -> {out_path}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
