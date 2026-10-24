#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transcribe WAV files offline with faster-whisper."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline transcription for extracted WAV files.")
    parser.add_argument("--wav-dir", required=True, help="Directory containing .wav files")
    parser.add_argument("--out", required=True, help="Directory for .txt transcripts")
    parser.add_argument("--model", default="small", help="faster-whisper model name or path")
    parser.add_argument("--language", default="zh", help="Language code, e.g. zh or en")
    parser.add_argument("--device", default="cpu", help="cpu or cuda")
    parser.add_argument("--compute-type", default="int8", help="int8, int8_float16, float16, float32")
    parser.add_argument("--limit", type=int, help="Maximum number of files to process")
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("missing dependency: pip install faster-whisper", file=sys.stderr)
        return 2

    wav_dir = Path(args.wav_dir)
    if not wav_dir.is_dir():
        parser.error(f"directory not found: {wav_dir}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    wavs = sorted(wav_dir.glob("*.wav"))
    if not wavs:
        print("no .wav files found", file=sys.stderr)
        return 1

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    done = 0
    for index, wav_path in enumerate(wavs, start=1):
        txt_path = out_dir / f"{wav_path.stem}.txt"
        if txt_path.exists():
            continue
        try:
            segments, _info = model.transcribe(str(wav_path), language=args.language)
            lines = [f"[{seg.start:.1f}-{seg.end:.1f}s] {seg.text.strip()}" for seg in segments]
            txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            done += 1
            print(f"  [{index}/{len(wavs)}] {wav_path.name}: {lines[0] if lines else '(empty)'}", file=sys.stderr)
        except Exception as exc:
            print(f"  [{index}/{len(wavs)}] {wav_path.name}: failed: {exc}", file=sys.stderr)
        if args.limit is not None and done >= args.limit:
            break

    print(f"done: {done} transcript(s) -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
