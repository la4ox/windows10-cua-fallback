"""Inspect and extract the legacy Windows workspace runtime without tar links.

This helper deliberately does not use extractall(). Only new regular files and
directories below one expected archive root are accepted.
"""
from __future__ import annotations

import argparse
import json
import lzma  # Fail early if this Python lacks the historical tar.xz support.
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile


MAX_EXPANDED_BYTES = 24 * 1024**3
MAX_MEMBERS = 250_000
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


def member_parts(name: str, root_name: str) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("archive member has an empty name or a backslash")
    while name.startswith("./"):
        name = name[2:]
    name = name.rstrip("/")
    parts = tuple(name.split("/"))
    if not parts or parts[0] != root_name:
        raise ValueError("archive member is outside the expected runtime root")
    for part in parts:
        if not part or part in (".", ".."):
            raise ValueError("archive member contains an unsafe path component")
        if part[-1:] in (".", " ") or re.search(r'[<>:"|?*\x00-\x1f]', part):
            raise ValueError("archive member is not a safe Windows path")
        if part.split(".", 1)[0].upper() in RESERVED:
            raise ValueError("archive member uses a reserved Windows device name")
    return parts


def inspect_members(
    archive: tarfile.TarFile,
    root_name: str,
    max_bytes: int = MAX_EXPANDED_BYTES,
) -> tuple[list[tuple[tarfile.TarInfo, tuple[str, ...]]], int]:
    if root_name != "codex-primary-runtime":
        raise ValueError("unexpected runtime root name")
    if max_bytes <= 0:
        raise ValueError("max-bytes must be positive")
    members: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
    paths: dict[str, str] = {}
    total = 0
    for member in archive:
        if len(members) >= MAX_MEMBERS:
            raise ValueError("archive has too many members")
        if not (member.isdir() or member.isfile()) or member.issparse():
            raise ValueError("archive links, sparse files and special files are not allowed")
        parts = member_parts(member.name, root_name)
        key = "/".join(parts).casefold()
        if key in paths:
            raise ValueError("archive contains duplicate or case-colliding paths")
        if member.size < 0 or (member.isdir() and member.size != 0):
            raise ValueError("archive member has an invalid size")
        total += member.size
        if total > max_bytes:
            raise ValueError("archive exceeds the expanded-byte limit")
        paths[key] = "directory" if member.isdir() else "file"
        members.append((member, parts))
    if not members:
        raise ValueError("archive is empty")
    for _, parts in members:
        for index in range(1, len(parts)):
            if paths.get("/".join(parts[:index]).casefold()) == "file":
                raise ValueError("archive file is also used as a parent directory")
    return members, total


def assert_plain_directory(directory: Path) -> None:
    for item in (directory, *directory.parents):
        if not item.exists() and not item.is_symlink():
            continue
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("extraction path contains a link or reparse point")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("extraction path contains a non-directory")


def extract_checked(
    archive: tarfile.TarFile,
    members: list[tuple[tarfile.TarInfo, tuple[str, ...]]],
    output: Path,
) -> None:
    assert_plain_directory(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("extraction output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    for member, parts in members:
        destination = output.joinpath(*parts)
        parent = destination if member.isdir() else destination.parent
        assert_plain_directory(parent)
        parent.mkdir(parents=True, exist_ok=True)
        assert_plain_directory(parent)
        if member.isdir():
            continue
        source = archive.extractfile(member)
        if source is None:
            raise ValueError("regular archive member has no data")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        with source, os.fdopen(os.open(destination, flags, 0o600), "wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        if destination.stat().st_size != member.size:
            raise ValueError("extracted file size does not match its tar header")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="report this Python without installing anything")
    for command in ("inspect", "extract"):
        action = sub.add_parser(command)
        action.add_argument("--archive", required=True)
        action.add_argument("--format", choices=("tar.gz", "tar.xz"), required=True)
        action.add_argument("--root-name", default="codex-primary-runtime")
        action.add_argument("--max-bytes", type=int, default=MAX_EXPANDED_BYTES)
        if command == "extract":
            action.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 10):
            raise ValueError("Python 3.10 or newer is required")
        if args.command == "probe":
            result = {"ok": True, "pythonExecutable": sys.executable,
                      "pythonVersion": sys.version.split()[0]}
        else:
            source = Path(args.archive).absolute()
            source_info = source.lstat()
            if not stat.S_ISREG(source_info.st_mode) or getattr(source_info, "st_file_attributes", 0) & 0x400:
                raise ValueError("archive must be a regular file, not a link")
            mode = "r:gz" if args.format == "tar.gz" else "r:xz"
            with tarfile.open(source, mode) as archive:
                members, total = inspect_members(archive, args.root_name, args.max_bytes)
                if args.command == "extract":
                    extract_checked(archive, members, Path(args.output).absolute())
            result = {"ok": True, "members": len(members), "expandedBytes": total,
                      "extracted": args.command == "extract"}
        print(json.dumps(result))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
