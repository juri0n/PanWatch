import json
import zipfile

import pytest

from scripts.crypto_backup import backup, verify, restore, MANIFEST


def test_backup_restore_no_overwrite(tmp_path):
    source = tmp_path / "appdata"
    source.mkdir()
    (source / "database.db").write_bytes(b"fixture database")
    (source / "database.db-wal").write_bytes(b"fixture wal")
    archive = tmp_path / "backup.zip"
    with pytest.raises(ValueError):
        backup(source, archive)
    manifest = backup(source, archive, stopped_confirmed=True)
    assert len(manifest) == 2 and verify(archive) == manifest
    recovered = tmp_path / "recovery"
    assert restore(archive, recovered) == manifest
    assert (recovered / "database.db-wal").read_bytes() == b"fixture wal"
    with pytest.raises(FileExistsError):
        restore(archive, recovered)
    with pytest.raises(FileExistsError):
        backup(source, archive, stopped_confirmed=True)


def test_corruption_and_traversal_rejected(tmp_path):
    for name in ["../escape", "/absolute", "C:/absolute", "folder\\escape", "valid"]:
        archive = tmp_path / f"bad{len(list(tmp_path.iterdir()))}.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(name, b"tampered")
            bundle.writestr(MANIFEST, json.dumps({name: "invalid-hash"}))
        with pytest.raises(ValueError):
            restore(archive, tmp_path / "new")
        assert not (tmp_path / "new").exists()
