from __future__ import annotations

import zipfile

import pytest

from scripts.backup import validate_output_path
from scripts.restore import validate_archive


def test_backup_output_must_not_overwrite_source_data(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with pytest.raises(ValueError, match="outside DATA_DIR"):
        validate_output_path(data_dir, data_dir / "metadata.sqlite")
    validate_output_path(data_dir, tmp_path / "safe-backup.zip")


def test_restore_archive_rejects_path_traversal_and_backslash_names(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "no")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="unsafe or unexpected"):
            validate_archive(archive)

    archive_path = tmp_path / "backslash.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("objects\\..\\outside.txt", "no")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="unsafe archive entry"):
            validate_archive(archive)


def test_restore_archive_rejects_duplicate_names_and_expansion_limit(tmp_path, monkeypatch):
    archive_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("vectors.json", "[]")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("vectors.json", "[]")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="duplicate archive entry"):
            validate_archive(archive)

    archive_path = tmp_path / "too-large.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("vectors.json", "0123456789")
    monkeypatch.setattr("scripts.restore.MAX_MEMBER_BYTES", 5)
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="size limit"):
            validate_archive(archive)


def test_restore_archive_rejects_file_directory_type_conflicts(tmp_path):
    archive_path = tmp_path / "wrong-root-type.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("metadata.sqlite/", "")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="file root cannot be a directory"):
            validate_archive(archive)

    archive_path = tmp_path / "objects-file.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("objects", "not a directory")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="directory root cannot be a regular file"):
            validate_archive(archive)

    archive_path = tmp_path / "ancestor-collision.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("objects/tenant", "file")
        archive.writestr("objects/tenant/file.txt", "child")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="descends from an earlier file"):
            validate_archive(archive)
