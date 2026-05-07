import zipfile
from pathlib import Path

import pytest

from garmin2fittrackee import ArchiveError
from garmin2fittrackee.garmin.archive import extract_archive


def create_test_zip(
    tmp_path: Path,
    name: str = "test_archive.zip",
    files: dict[str, str] | None = None,
) -> Path:
    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w") as zf:
        entries = files or {
            "testdir/file1.txt": "hello",
            "testdir/file2.json": '{"key": "value"}',
        }
        for fname, content in entries.items():
            zf.writestr(fname, content)
    return archive


@pytest.fixture
def test_zip(tmp_path: Path) -> Path:
    return create_test_zip(tmp_path)


@pytest.fixture
def extract_folder(tmp_path: Path) -> Path:
    return tmp_path / "exports"


class TestExtractArchive:
    def test_extracts_to_subfolder_named_after_archive(
        self,
        test_zip: Path,
        extract_folder: Path,
    ) -> None:
        result = extract_archive(test_zip, extract_folder)
        assert result == extract_folder / "test_archive"
        assert result.exists()
        assert (result / "testdir" / "file1.txt").read_text() == "hello"
        assert (
            (result / "testdir" / "file2.json").read_text()
            == '{"key": "value"}'
        )

    def test_creates_extract_folder_if_not_exists(
        self,
        test_zip: Path,
        extract_folder: Path,
    ) -> None:
        assert not extract_folder.exists()
        extract_archive(test_zip, extract_folder)
        assert extract_folder.exists()

    def test_raises_on_missing_archive(
        self,
        extract_folder: Path,
    ) -> None:
        with pytest.raises(ArchiveError, match="Archive not found"):
            extract_archive(
                Path("/nonexistent/file.zip"),
                extract_folder,
            )

    def test_raises_on_non_zip_file(
        self,
        tmp_path: Path,
        extract_folder: Path,
    ) -> None:
        bad_file = tmp_path / "not_a_zip.txt"
        bad_file.write_text("not a zip file")
        with pytest.raises(ArchiveError, match="Not a valid ZIP archive"):
            extract_archive(bad_file, extract_folder)

    def test_raises_on_directory_instead_of_file(
        self,
        tmp_path: Path,
        extract_folder: Path,
    ) -> None:
        a_dir = tmp_path / "adir"
        a_dir.mkdir()
        with pytest.raises(ArchiveError, match="Not a file"):
            extract_archive(a_dir, extract_folder)

    def test_overwrites_existing_target(
        self,
        test_zip: Path,
        extract_folder: Path,
    ) -> None:
        target = extract_folder / "test_archive"
        extract_archive(test_zip, extract_folder)
        assert target.exists()
        extract_archive(test_zip, extract_folder)
        assert target.exists()

    def test_preserves_nested_directories(
        self,
        tmp_path: Path,
        extract_folder: Path,
    ) -> None:
        archive = create_test_zip(
            tmp_path,
            files={
                "DI_CONNECT/DI-Connect-Wellness/data.json": (
                    '{"status": "ok"}'
                ),
                "DI_CONNECT/DI-Connect-Metrics/score.json": (
                    '{"score": 42}'
                ),
                "customer_data/customer.json": '{"name": "test"}',
            },
        )
        result = extract_archive(archive, extract_folder)
        wellness = (
            result
            / "DI_CONNECT"
            / "DI-Connect-Wellness"
            / "data.json"
        )
        assert wellness.read_text() == '{"status": "ok"}'
        metrics = (
            result
            / "DI_CONNECT"
            / "DI-Connect-Metrics"
            / "score.json"
        )
        assert metrics.read_text() == '{"score": 42}'
        customer = result / "customer_data" / "customer.json"
        assert customer.read_text() == '{"name": "test"}'

    def test_extracts_nested_zips(
        self,
        tmp_path: Path,
        extract_folder: Path,
    ) -> None:
        inner_zip_path = tmp_path / "inner.zip"
        with zipfile.ZipFile(inner_zip_path, "w") as izf:
            izf.writestr("activity1.fit", "fit-data-1")
            izf.writestr("activity2.fit", "fit-data-2")

        archive = create_test_zip(
            tmp_path,
            files={
                "DI_CONNECT/data.zip": inner_zip_path.read_bytes(),
                "top.txt": "plain",
            },
        )
        result = extract_archive(archive, extract_folder)
        inner_dir = result / "DI_CONNECT" / "data"
        assert inner_dir.exists()
        assert (inner_dir / "activity1.fit").read_text() == "fit-data-1"
        assert (inner_dir / "activity2.fit").read_text() == "fit-data-2"
        assert not (result / "DI_CONNECT" / "data.zip").exists()
        assert (result / "top.txt").read_text() == "plain"

    def test_skips_invalid_nested_zip(
        self,
        tmp_path: Path,
        extract_folder: Path,
    ) -> None:
        archive = create_test_zip(
            tmp_path,
            files={
                "bad.zip": "not a real zip",
                "good.txt": "ok",
            },
        )
        result = extract_archive(archive, extract_folder)
        assert (result / "good.txt").read_text() == "ok"
        assert not (result / "bad.zip").exists()
