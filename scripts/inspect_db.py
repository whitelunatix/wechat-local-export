#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect a decrypted WeChat 4.x SQLite database.

Prints table names, columns and row counts. It does not read message contents.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def inspect(path: Path) -> None:
    con = connect_readonly(path)
    try:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        print(f"\n{path.name}  ({path})")
        if not tables:
            print("  (no user tables)")
            return
        for table in tables:
            columns = [row[1] for row in con.execute(f"PRAGMA table_info({quote_identifier(table)})")]
            count = con.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0]
            print(f"  {table}  rows={count}")
            print(f"    columns: {', '.join(columns) if columns else '(none)'}")
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect decrypted WeChat 4.x SQLite databases.")
    parser.add_argument("--db", action="append", default=[], help="Path to a .decrypted.db file (repeatable).")
    parser.add_argument("--dir", help="Directory containing *.decrypted.db files.")
    args = parser.parse_args()

    paths = [Path(p) for p in args.db]
    if args.dir:
        paths.extend(sorted(Path(args.dir).glob("*.decrypted.db")))
    if not paths:
        parser.error("provide --db and/or --dir")

    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.is_file():
            print(f"skip (not found): {path}", file=sys.stderr)
            continue
        try:
            inspect(path)
        except sqlite3.Error as exc:
            print(f"skip ({exc}): {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
