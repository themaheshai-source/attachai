#!/usr/bin/env python3
"""Create a local Orbit AI data backup without copying a live SQLite file byte-for-byte."""
from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def validate_output_path(data_dir: Path, output: Path) -> None:
    """Prevent a backup archive from overwriting files inside its source data tree."""
    if output == data_dir or data_dir in output.parents:
        raise ValueError(f"backup output must be outside DATA_DIR to avoid overwriting live data: {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("DATA_DIR", "./data")))
    parser.add_argument("--output", type=Path, help="Destination zip; defaults to orbit-backup-<UTC timestamp>.zip")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        parser.error(f"data directory does not exist: {data_dir}")
    output = (args.output or Path(f"orbit-backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip")).resolve()
    try:
        validate_output_path(data_dir, output)
    except ValueError as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="orbit-backup-") as tmp_name:
        staged = Path(tmp_name)
        db = data_dir / "metadata.sqlite"
        if db.is_file():
            source = sqlite3.connect(db)
            destination = sqlite3.connect(staged / "metadata.sqlite")
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
                source.close()
        for name in ("vectors.json", "objects", "outbox"):
            source = data_dir / name
            destination = staged / name
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
            elif source.is_dir():
                import shutil
                shutil.copytree(source, destination)
        if not any(staged.iterdir()):
            parser.error(f"no recognized Orbit AI data files found in {data_dir}")
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(staged.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staged).as_posix())
    if os.name != "nt":
        os.chmod(output, 0o600)
    print(f"Backup created: {output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
