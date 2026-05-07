import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from garmin2fittrackee import ArchiveError
from garmin2fittrackee.cli import _resolve_archive_path, app

runner = CliRunner()


class TestExtractCLI:
    def test_extract_command_success(
        self,
        tmp_path: Path,
        test_zip: Path,
    ) -> None:
        extract_folder = tmp_path / "output"
        result = runner.invoke(
            app,
            [
                "extract",
                str(test_zip),
                "--extract-folder",
                str(extract_folder),
            ],
        )
        assert result.exit_code == 0
        assert "Archive extracted to:" in result.output
        assert str(extract_folder / "test_archive") in result.output

    def test_extract_command_default_folder(
        self,
        test_zip: Path,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv(
            "GARMIN_EXTRACT_FOLDER",
            str(tmp_path / "default_exports"),
        )
        result = runner.invoke(app, ["extract", str(test_zip)])
        assert result.exit_code == 0
        assert "Archive extracted to:" in result.output

    def test_extract_command_missing_archive(
        self,
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(
            app,
            ["extract", str(tmp_path / "nonexistent.zip")],
        )
        assert result.exit_code != 0


class TestResolveArchivePath:
    def test_returns_directory_as_is(self, tmp_path: Path) -> None:
        result = _resolve_archive_path(tmp_path)
        assert result == tmp_path

    def test_extracts_zip_file(self, tmp_path: Path) -> None:
        extract_dest = tmp_path / "exports"
        extract_dest.mkdir()

        archive = tmp_path / "my_export.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("data/file.txt", "hello")

        with patch(
            "garmin2fittrackee.cli.DEFAULT_EXTRACT_FOLDER", extract_dest
        ):
            result = _resolve_archive_path(archive)

        assert result == extract_dest / "my_export"
        assert (result / "data" / "file.txt").read_text() == "hello"

    def test_raises_on_nonexistent_path(self) -> None:
        with pytest.raises(ArchiveError, match="Path not found"):
            _resolve_archive_path(Path("/nonexistent/path"))

    def test_raises_on_non_zip_file(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "data.txt"
        bad_file.write_text("not a zip")
        with pytest.raises(ArchiveError, match="Not a valid ZIP archive"):
            _resolve_archive_path(bad_file)


class TestSyncCommandsWithZip:
    def test_sync_equipments_accepts_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FITTRACKEE_URL", "http://localhost")
        monkeypatch.setenv("FITTRACKEE_USERNAME", "user")
        monkeypatch.setenv("FITTRACKEE_PASSWORD", "pass")

        result = runner.invoke(
            app,
            [
                "sync-equipments",
                str(tmp_path),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "No gear files found" in result.output

    def test_sync_equipments_accepts_zip(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FITTRACKEE_URL", "http://localhost")
        monkeypatch.setenv("FITTRACKEE_USERNAME", "user")
        monkeypatch.setenv("FITTRACKEE_PASSWORD", "pass")

        extract_dest = tmp_path / "exports"
        extract_dest.mkdir()

        archive = tmp_path / "garmin.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("data/file.txt", "hello")

        with patch(
            "garmin2fittrackee.cli.DEFAULT_EXTRACT_FOLDER", extract_dest
        ):
            result = runner.invoke(
                app,
                [
                    "sync-equipments",
                    str(archive),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0
        assert "Auto-extracted archive to:" in result.output

    def test_sync_equipments_rejects_non_zip_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FITTRACKEE_URL", "http://localhost")
        monkeypatch.setenv("FITTRACKEE_USERNAME", "user")
        monkeypatch.setenv("FITTRACKEE_PASSWORD", "pass")

        bad_file = tmp_path / "data.txt"
        bad_file.write_text("not a zip")

        result = runner.invoke(
            app,
            [
                "sync-equipments",
                str(bad_file),
                "--dry-run",
            ],
        )
        assert result.exit_code != 0

    def test_sync_activities_accepts_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FITTRACKEE_URL", "http://localhost")
        monkeypatch.setenv("FITTRACKEE_USERNAME", "user")
        monkeypatch.setenv("FITTRACKEE_PASSWORD", "pass")

        result = runner.invoke(
            app,
            [
                "sync-activities",
                str(tmp_path),
                "--dry-run",
            ],
        )
        assert result.exit_code != 0

    def test_sync_activities_accepts_zip_and_auto_extracts(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FITTRACKEE_URL", "http://localhost")
        monkeypatch.setenv("FITTRACKEE_USERNAME", "user")
        monkeypatch.setenv("FITTRACKEE_PASSWORD", "pass")

        extract_dest = tmp_path / "exports"
        extract_dest.mkdir()

        archive = tmp_path / "garmin.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("data/file.txt", "hello")

        with patch(
            "garmin2fittrackee.cli.DEFAULT_EXTRACT_FOLDER", extract_dest
        ):
            result = runner.invoke(
                app,
                [
                    "sync-activities",
                    str(archive),
                    "--dry-run",
                ],
            )

        assert "Auto-extracted archive to:" in result.output
        assert extract_dest.exists()

    def test_sync_activities_rejects_non_zip_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FITTRACKEE_URL", "http://localhost")
        monkeypatch.setenv("FITTRACKEE_USERNAME", "user")
        monkeypatch.setenv("FITTRACKEE_PASSWORD", "pass")

        bad_file = tmp_path / "data.txt"
        bad_file.write_text("not a zip")

        result = runner.invoke(
            app,
            [
                "sync-activities",
                str(bad_file),
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
