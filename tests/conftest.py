import zipfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("LOG_DIR", str(log_dir))


@pytest.fixture
def test_zip(tmp_path: Path) -> Path:
    archive = tmp_path / "test_archive.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("testdir/file1.txt", "hello")
        zf.writestr("testdir/file2.json", '{"key": "value"}')
    return archive
