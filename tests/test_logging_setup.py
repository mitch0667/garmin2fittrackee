import logging
from pathlib import Path

from garmin2fittrackee.logging_setup import setup_logging


class TestSetupLogging:
    def test_creates_console_handler_at_warning(self) -> None:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.setLevel(logging.NOTSET)

        import garmin2fittrackee.logging_setup as mod
        mod._root_configured = False

        setup_logging()

        assert root.level == logging.DEBUG
        console_handlers = [
            h for h in root.handlers if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.CRITICAL

    def test_creates_file_handler_when_path_given(self, tmp_path: Path) -> None:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.setLevel(logging.NOTSET)

        import garmin2fittrackee.logging_setup as mod
        mod._root_configured = False

        log_path = tmp_path / "test.log"
        setup_logging(log_path)

        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.DEBUG
        assert log_path.exists()

    def test_file_handler_writes_logs(self, tmp_path: Path) -> None:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.setLevel(logging.NOTSET)

        import garmin2fittrackee.logging_setup as mod
        mod._root_configured = False

        log_path = tmp_path / "test.log"
        setup_logging(log_path)

        test_logger = logging.getLogger("test.module")
        test_logger.info("test message 123")

        content = log_path.read_text()
        assert "test message 123" in content

    def test_idempotent(self, tmp_path: Path) -> None:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.setLevel(logging.NOTSET)

        import garmin2fittrackee.logging_setup as mod
        mod._root_configured = False

        setup_logging(tmp_path / "a.log")
        setup_logging(tmp_path / "b.log")

        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
