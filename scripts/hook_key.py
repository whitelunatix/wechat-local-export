#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture the WeChat 4.x database passphrase through a user-supplied hook DLL.

The DLL is not part of this repository.  Its exports must match the small
interface described in docs/key-extraction.md:

    InitializeHook(uint32 pid) -> bool
    PollKeyData(char *buf, int cap) -> bool
    GetStatusMessage(char *buf, int cap, int *level) -> bool
    CleanupHook() -> bool
    GetLastErrorMsg() -> const char *

Only run this against a WeChat account you own and are authorized to export.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import stat
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - handled with a clear message
    psutil = None


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def find_process(name: str, marker: str | None) -> int:
    """Return the PID that owns ``marker``, falling back to the first match."""
    if psutil is None:
        raise RuntimeError("psutil is required: pip install psutil")

    matches: list[int] = []
    holders: list[int] = []
    wanted = name.lower()
    for proc in psutil.process_iter(["pid", "name"]):
        info = proc.info
        if not info.get("name") or info["name"].lower() != wanted:
            continue
        matches.append(info["pid"])
        if not marker:
            continue
        try:
            for opened in proc.open_files():
                if marker.lower() in opened.path.lower():
                    holders.append(info["pid"])
                    break
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue

    if holders:
        return holders[0]
    if matches:
        return matches[0]
    raise RuntimeError(f"process not found: {name}")


class KeyHook:
    def __init__(self, dll_path: Path) -> None:
        self.dll = ctypes.CDLL(str(dll_path))
        self.dll.InitializeHook.argtypes = [ctypes.c_uint32]
        self.dll.InitializeHook.restype = ctypes.c_bool
        self.dll.PollKeyData.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.dll.PollKeyData.restype = ctypes.c_bool
        self.dll.GetStatusMessage.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.GetStatusMessage.restype = ctypes.c_bool
        self.dll.CleanupHook.argtypes = []
        self.dll.CleanupHook.restype = ctypes.c_bool
        self.dll.GetLastErrorMsg.argtypes = []
        self.dll.GetLastErrorMsg.restype = ctypes.c_char_p
        self._initialized = False

    def start(self, pid: int) -> None:
        if not self.dll.InitializeHook(pid):
            raise RuntimeError(self.last_error() or "InitializeHook failed")
        self._initialized = True

    def poll(self, timeout: float) -> str | None:
        key_buf = ctypes.create_string_buffer(128)
        log_buf = ctypes.create_string_buffer(512)
        level = ctypes.c_int()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self.dll.PollKeyData(key_buf, len(key_buf)):
                key = key_buf.value.decode("ascii", errors="replace").strip()
                if key:
                    return key
            while self.dll.GetStatusMessage(log_buf, len(log_buf), ctypes.byref(level)):
                message = log_buf.value.decode("utf-8", errors="replace")
                print(f"  [dll] {message}")
            time.sleep(0.2)
        return None

    def last_error(self) -> str:
        raw = self.dll.GetLastErrorMsg()
        return raw.decode("utf-8", errors="replace") if raw else ""

    def close(self) -> None:
        if self._initialized:
            try:
                self.dll.CleanupHook()
            finally:
                self._initialized = False


def write_key(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="ascii")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path, help="path to your hook DLL")
    parser.add_argument("--process", default="Weixin.exe", help="process name to attach to")
    parser.add_argument(
        "--marker",
        default="message_0.db",
        help="prefer the process holding this file; pass an empty string to disable",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="polling timeout in seconds")
    parser.add_argument("--out", type=Path, help="write the key to this file instead of stdout")
    args = parser.parse_args()

    if not args.dll.is_file():
        print(f"[-] DLL not found: {args.dll}", file=sys.stderr)
        return 2

    try:
        pid = find_process(args.process, args.marker or None)
    except RuntimeError as exc:
        print(f"[-] {exc}", file=sys.stderr)
        return 1

    print(f"[+] target process: {args.process} (pid={pid})")
    print(f"[+] loading: {args.dll}")
    hook: KeyHook | None = None
    try:
        hook = KeyHook(args.dll)
        hook.start(pid)
        print("[+] hook installed; open or switch a chat to trigger a database key operation")
        key = hook.poll(args.timeout)
    except Exception as exc:
        print(f"[-] {exc}", file=sys.stderr)
        return 1
    finally:
        if hook is not None:
            hook.close()

    if not key:
        print(f"[-] timed out after {args.timeout:g}s", file=sys.stderr)
        return 1

    if args.out:
        write_key(args.out, key)
        print(f"[+] key written to {args.out}")
        print("[!] keep this file private and delete it when you are done")
    else:
        print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
