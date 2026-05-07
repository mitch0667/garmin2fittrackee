import os
from pathlib import Path
from unittest.mock import patch

import garmin2fittrackee.config as cfg


class TestConfig:
    def test_default_extract_folder(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from garmin2fittrackee.config import DEFAULT_EXTRACT_FOLDER

            assert DEFAULT_EXTRACT_FOLDER == Path("/tmp/garmin_exports")

    def test_custom_extract_folder_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {"GARMIN_EXTRACT_FOLDER": "/custom/path"},
        ):
            import importlib

            importlib.reload(cfg)
            assert cfg.DEFAULT_EXTRACT_FOLDER == Path("/custom/path")

            importlib.reload(cfg)


class TestDefaultLogFile:
    def test_default_generates_timestamped_name(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            path = cfg.default_log_file()
            assert str(path).startswith("logs/garmin2fittrackee_")
            assert path.name.startswith("garmin2fittrackee_")
            assert path.name.endswith(".log")

    def test_env_override_returns_static_path(self) -> None:
        with patch.dict(os.environ, {"LOG_FILE": "/tmp/custom.log"}):
            assert cfg.default_log_file() == Path("/tmp/custom.log")

    def test_log_dir_env_var(self) -> None:
        with patch.dict(os.environ, {"LOG_DIR": "/var/log/app"}, clear=True):
            path = cfg.default_log_file()
            assert str(path).startswith("/var/log/app/garmin2fittrackee_")
