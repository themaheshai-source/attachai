#!/usr/bin/env python3
"""Restore a backup made by scripts/backup.py. Stop Orbit AI before running."""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import stat

ALLOWED_ROOTS = {"metadata.sqlite", "vectors.json", "objects", "outbox"}
MAX_ARCHIVE_ENTRIES = 100_000
MAX_MEMBER_BYTES = 5 * 1024**3
MAX_TOTAL_BYTES = 10 * 1024**3


def validate_archive(archive: zipfile.ZipFile) -> None:
    """Reject unsafe archive names/types and excessive expansion before extraction."""
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ValueError(f"archive has too many entries (limit {MAX_ARCHIVE_ENTRIES})")
    seen: set[str] = set()
    seen_kinds: dict[str, bool] = {}
    total_size = 0
    for info in infos:
        raw_name = info.filename
        if not raw_name or "\\" in raw_name or "\x00" in raw_name or raw_name.startswith("/"):
            raise ValueError(f"unsafe archive entry: {raw_name!r}")
        name = PurePosixPath(raw_name)
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if (name.is_absolute() or ".." in name.parts or "." in name.parts or not name.parts
                or name.parts[0] not in ALLOWED_ROOTS or file_type == stat.S_IFLNK
                or file_type not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError(f"unsafe or unexpected archive entry: {raw_name}")
        normalized = name.as_posix().rstrip("/")
        is_directory = info.is_dir() or file_type == stat.S_IFDIR
        if name.parts[0] in {"metadata.sqlite", "vectors.json"} and (len(name.parts) > 1 or is_directory):
            raise ValueError(f"file root cannot be a directory or contain descendants: {raw_name}")
        if len(name.parts) == 1 and name.parts[0] in {"objects", "outbox"} and not is_directory:
            raise ValueError(f"directory root cannot be a regular file: {raw_name}")
        if normalized in seen:
            raise ValueError(f"duplicate archive entry: {raw_name}")
        # A ZIP must not declare a regular file and also place descendants beneath it.
        for ancestor_count in range(1, len(name.parts)):
            ancestor = PurePosixPath(*name.parts[:ancestor_count]).as_posix()
            if ancestor in seen_kinds and not seen_kinds[ancestor]:
                raise ValueError(f"archive entry descends from an earlier file: {raw_name}")
        if not is_directory and any(existing.startswith(normalized + "/") for existing in seen):
            raise ValueError(f"archive entry conflicts with an earlier descendant: {raw_name}")
        seen.add(normalized)
        seen_kinds[normalized] = is_directory
        if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"archive member exceeds the size limit: {raw_name}")
        total_size += info.file_size
        if total_size > MAX_TOTAL_BYTES:
            raise ValueError(f"archive exceeds the total expanded size limit ({MAX_TOTAL_BYTES} bytes)")
        if info.flag_bits & 1:
            raise ValueError("encrypted backup entries are not supported")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("DATA_DIR", "./data")))
    parser.add_argument("--force", action="store_true", help="Allow overwriting existing local data")
    args = parser.parse_args()
    archive_path = args.archive.resolve()
    data_dir = args.data_dir.resolve()
    if not archive_path.is_file():
        parser.error(f"backup archive not found: {archive_path}")
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        try:
            validate_archive(archive)
        except ValueError as exc:
            parser.error(str(exc))
        if data_dir.exists() and any(data_dir.iterdir()) and not args.force:
            parser.error(f"destination is not empty; use --force only after making a backup: {data_dir}")
        with tempfile.TemporaryDirectory(prefix="orbit-restore-", dir=data_dir.parent) as tmp_name:
            staged = Path(tmp_name) / "staged"
            staged.mkdir()
            archive.extractall(staged)
            # Verify no empty or corrupt SQLite file before modifying the target.
            db = staged / "metadata.sqlite"
            if db.is_file():
                import sqlite3
                with sqlite3.connect(db) as conn:
                    result = conn.execute("PRAGMA quick_check").fetchone()
                if not result or result[0] != "ok":
                    parser.error("backup SQLite integrity check failed; destination was not changed")
            if data_dir.exists() and any(data_dir.iterdir()):
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = data_dir.with_name(data_dir.name + f".pre-restore-{stamp}")
                shutil.copytree(data_dir, backup)
                print(f"Pre-restore data backup: {backup}")
            data_dir.mkdir(parents=True, exist_ok=True)
            for child in staged.iterdir():
                destination = data_dir / child.name
                if destination.is_dir():
                    shutil.rmtree(destination)
                elif destination.exists():
                    destination.unlink()
                if child.is_dir():
                    shutil.copytree(child, destination)
                else:
                    shutil.copy2(child, destination)
    print(f"Restored data to: {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
