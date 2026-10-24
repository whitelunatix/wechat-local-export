#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decrypt WeChat 4.x SQLCipher 4 databases.

The database passphrase captured by ``hook_key.py`` is a 32-byte raw key
(64 hex characters).  Every database file has its own 16-byte salt in the
first page, so the raw key is derived per file:

    raw_key = PBKDF2-HMAC-SHA512(passphrase, salt, 256000, 32)

Each 4096-byte page stores ciphertext, a 16-byte IV and a 64-byte HMAC.
See docs/sqlcipher.md for the page layout and verification details.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import sys
from pathlib import Path

try:
    from Crypto.Cipher import AES
except ImportError:  # pragma: no cover - handled with a clear message
    AES = None

PAGE_SIZE = 4096
SALT_SIZE = 16
IV_SIZE = 16
HMAC_SIZE = 64
RESERVE_SIZE = 80  # IV + HMAC, rounded up to an AES block
KDF_ITERATIONS = 256_000
MAC_KDF_ITERATIONS = 2
SQLITE_HEADER = b"SQLite format 3\x00"
HEX_KEY_RE = re.compile(r"[0-9a-fA-F]{64}")


def read_passphrase(path: Path) -> bytes:
    text = path.read_text(encoding="ascii", errors="ignore")
    match = HEX_KEY_RE.search(text)
    if not match:
        raise ValueError(f"no 64-character hex key found in {path}")
    return bytes.fromhex(match.group(0))


def derive_keys(passphrase: bytes, salt: bytes) -> tuple[bytes, bytes]:
    raw_key = hashlib.pbkdf2_hmac("sha512", passphrase, salt, KDF_ITERATIONS, dklen=32)
    mac_salt = bytes(value ^ 0x3A for value in salt)
    mac_key = hashlib.pbkdf2_hmac(
        "sha512", raw_key, mac_salt, MAC_KDF_ITERATIONS, dklen=32
    )
    return raw_key, mac_key


def page_mac(mac_key: bytes, page: bytes, page_number: int) -> bytes:
    if page_number == 1:
        ciphertext = page[SALT_SIZE:-RESERVE_SIZE]
    else:
        ciphertext = page[:-RESERVE_SIZE]
    iv = page[-RESERVE_SIZE : -RESERVE_SIZE + IV_SIZE]
    digest = hmac.new(mac_key, digestmod="sha512")
    digest.update(ciphertext)
    digest.update(iv)
    digest.update(page_number.to_bytes(4, "little"))
    return digest.digest()


def decrypt_bytes(data: bytes, passphrase: bytes) -> bytes:
    if AES is None:
        raise RuntimeError("pycryptodome is required: pip install pycryptodome")
    if len(data) < PAGE_SIZE or len(data) % PAGE_SIZE:
        raise ValueError("database size is not a multiple of 4096 bytes")

    salt = data[:SALT_SIZE]
    raw_key, mac_key = derive_keys(passphrase, salt)
    output = bytearray(SQLITE_HEADER)
    pages = len(data) // PAGE_SIZE

    for index in range(pages):
        page = data[index * PAGE_SIZE : (index + 1) * PAGE_SIZE]
        page_number = index + 1
        expected = page_mac(mac_key, page, page_number)
        if not hmac.compare_digest(expected, page[-HMAC_SIZE:]):
            raise ValueError(f"HMAC verification failed on page {page_number}")

        iv = page[-RESERVE_SIZE : -RESERVE_SIZE + IV_SIZE]
        if page_number == 1:
            ciphertext = page[SALT_SIZE:-RESERVE_SIZE]
        else:
            ciphertext = page[:-RESERVE_SIZE]
        plaintext = AES.new(raw_key, AES.MODE_CBC, iv).decrypt(ciphertext)
        output.extend(plaintext)
        output.extend(page[-RESERVE_SIZE:])

    return bytes(output)


def output_path_for(db_path: Path, source_root: Path, out_dir: Path | None) -> Path:
    if out_dir is None:
        return db_path.with_name(db_path.name[:-3] + ".decrypted.db")
    relative = db_path.relative_to(source_root)
    target = out_dir / relative
    return target.with_name(target.name[:-3] + ".decrypted.db")


def decrypt_file(
    db_path: Path,
    passphrase: bytes,
    out_path: Path,
    *,
    force: bool,
    quiet: bool,
) -> str:
    if out_path.exists() and not force:
        return "skipped"
    if not quiet:
        print(f"  [..] {db_path}")
    data = db_path.read_bytes()
    plaintext = decrypt_bytes(data, passphrase)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(out_path.name + ".tmp")
    try:
        temp_path.write_bytes(plaintext)
        os.replace(temp_path, out_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    if not quiet:
        print(f"  [OK] {out_path}")
    return "ok"


def iter_databases(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.db")
        if path.is_file() and not path.name.endswith(".decrypted.db")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path, help="decrypt one .db file")
    source.add_argument("--dir", type=Path, help="decrypt every .db under this directory")
    parser.add_argument("--key-file", required=True, type=Path, help="file containing the 64-hex passphrase")
    parser.add_argument("--out", type=Path, help="output path for --db")
    parser.add_argument("--out-dir", type=Path, help="mirror the directory tree under this path")
    parser.add_argument("--force", action="store_true", help="overwrite existing .decrypted.db files")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if AES is None:
        print("[-] pycryptodome is required: pip install pycryptodome", file=sys.stderr)
        return 2

    try:
        passphrase = read_passphrase(args.key_file)
    except (OSError, ValueError) as exc:
        print(f"[-] {exc}", file=sys.stderr)
        return 2

    if args.db:
        if not args.db.is_file():
            print(f"[-] not a file: {args.db}", file=sys.stderr)
            return 2
        out_path = args.out or output_path_for(args.db, args.db.parent, None)
        if args.out_dir:
            out_path = output_path_for(args.db, args.db.parent, args.out_dir)
        try:
            result = decrypt_file(
                args.db, passphrase, out_path, force=args.force, quiet=args.quiet
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"[-] {args.db}: {exc}", file=sys.stderr)
            return 1
        if result == "skipped":
            print(f"[=] exists, use --force: {out_path}")
        return 0

    if not args.dir.is_dir():
        print(f"[-] not a directory: {args.dir}", file=sys.stderr)
        return 2

    databases = iter_databases(args.dir)
    if not databases:
        print(f"[-] no .db files under {args.dir}", file=sys.stderr)
        return 1

    counts = {"ok": 0, "skipped": 0, "failed": 0}
    for db_path in databases:
        out_path = output_path_for(db_path, args.dir, args.out_dir)
        try:
            result = decrypt_file(
                db_path, passphrase, out_path, force=args.force, quiet=args.quiet
            )
        except (OSError, ValueError, RuntimeError) as exc:
            counts["failed"] += 1
            print(f"  [FAIL] {db_path}: {exc}", file=sys.stderr)
            continue
        counts[result] += 1

    print(
        f"[+] done: {counts['ok']} decrypted, "
        f"{counts['skipped']} skipped, {counts['failed']} failed"
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
