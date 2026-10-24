#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract WeChat 4.x voice messages from a decrypted media database.

Input: media_0.decrypted.db containing Name2Id and VoiceInfo.
Output: WAV files (24 kHz mono 16-bit) and manifest.jsonl.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
import wave
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def load_names(con: sqlite3.Connection) -> dict[int, str]:
    try:
        rows = con.execute("SELECT rowid, user_name FROM Name2Id").fetchall()
    except sqlite3.Error:
        return {}
    return {int(rowid): str(name) for rowid, name in rows if name}


def ensure_wav(path: Path, duration: float | None) -> float | None:
    """pilk may emit raw PCM; add a 24 kHz mono 16-bit WAV header when needed."""
    data = path.read_bytes()
    if data[:4] == b"RIFF":
        if duration is not None:
            return duration
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / rate if rate else None
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(data)
    return len(data) / 2 / 24000


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract WeChat 4.x voice messages.")
    parser.add_argument("--db", required=True, help="Path to media_0.decrypted.db")
    parser.add_argument("--out", required=True, help="Output directory for WAV files")
    parser.add_argument("--chat", default="all", help="'all' or a user_name from Name2Id")
    parser.add_argument("--limit", type=int, help="Maximum number of voices to extract")
    parser.add_argument("--keep-silk", action="store_true", help="Keep intermediate .silk files")
    parser.add_argument("--anonymize", action="store_true", help="Hash session names in manifest.jsonl")
    args = parser.parse_args()

    try:
        import pilk
    except ImportError:
        print("missing dependency: pip install pilk", file=sys.stderr)
        return 2

    db_path = Path(args.db)
    if not db_path.is_file():
        parser.error(f"database not found: {db_path}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = connect_readonly(db_path)
    try:
        columns = [row[1] for row in con.execute("PRAGMA table_info(VoiceInfo)")]
        required = {"chat_name_id", "voice_data"}
        if not required.issubset(columns):
            print(f"VoiceInfo missing columns: {sorted(required - set(columns))}", file=sys.stderr)
            return 1

        names = load_names(con)
        selected = [c for c in ("chat_name_id", "create_time", "local_id", "svr_id", "voice_data") if c in columns]
        sql = f"SELECT {', '.join(quote_identifier(c) for c in selected)} FROM VoiceInfo"
        params: list[Any] = []
        if args.chat.lower() != "all":
            rows = con.execute("SELECT rowid FROM Name2Id WHERE user_name=?", (args.chat,)).fetchone()
            if not rows:
                print(f"chat not found in Name2Id: {args.chat}", file=sys.stderr)
                return 1
            sql += " WHERE chat_name_id=?"
            params.append(rows[0])
        sql += " ORDER BY chat_name_id, create_time, local_id"

        manifest_path = out_dir / "manifest.jsonl"
        written = 0
        with manifest_path.open("w", encoding="utf-8") as manifest:
            for row in con.execute(sql, params):
                record = dict(zip(selected, row))
                voice_data = record.get("voice_data")
                if not voice_data:
                    continue
                if isinstance(voice_data, memoryview):
                    voice_data = voice_data.tobytes()
                chat_id = record.get("chat_name_id")
                session = names.get(int(chat_id), f"chat_{chat_id}") if chat_id is not None else "unknown"
                if args.anonymize:
                    session = hashlib.sha256(session.encode("utf-8")).hexdigest()[:12]

                create_time = record.get("create_time")
                try:
                    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(int(create_time)))
                except (TypeError, ValueError, OSError):
                    stamp = "unknown"
                stem = f"voice_{written:05d}_{stamp}"
                silk_path = out_dir / f"{stem}.silk"
                wav_path = out_dir / f"{stem}.wav"
                silk_path.write_bytes(voice_data)
                try:
                    duration = pilk.decode(str(silk_path), str(wav_path))
                    duration = ensure_wav(wav_path, duration)
                except Exception as exc:
                    print(f"  [{written}] decode failed: {exc}", file=sys.stderr)
                    silk_path.unlink(missing_ok=True)
                    continue
                if not args.keep_silk:
                    silk_path.unlink(missing_ok=True)

                manifest.write(
                    json.dumps(
                        {
                            "index": written,
                            "session": session,
                            "create_time": create_time,
                            "local_id": record.get("local_id"),
                            "duration": round(float(duration), 2) if duration is not None else None,
                            "wav": wav_path.name,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                written += 1
                if written % 100 == 0:
                    print(f"  extracted {written}", file=sys.stderr)
                if args.limit is not None and written >= args.limit:
                    break

        print(f"done: {written} voice(s) -> {out_dir} (manifest: {manifest_path.name})")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
