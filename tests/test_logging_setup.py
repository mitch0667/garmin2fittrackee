import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from garmin2fittrackee.logging_setup import setup_logging

_THIRD_PARTY_LOGGERS = ("httpcore", "httpcore.http11", "httpcore.connection", "httpx")


def _reset_logging() -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.NOTSET)

    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)

    import garmin2fittrackee.logging_setup as mod

    mod._root_configured = False


class TestSetupLogging:
    def test_creates_console_handler_at_critical(self) -> None:
        _reset_logging()
        setup_logging()

        root = logging.getLogger()
        assert root.level == logging.DEBUG
        console_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.CRITICAL

    def test_creates_file_handler_when_path_given(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        setup_logging(log_path)

        file_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.DEBUG
        assert log_path.exists()

    def test_file_handler_writes_logs(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        setup_logging(log_path)

        test_logger = logging.getLogger("test.module")
        test_logger.info("test message 123")

        content = log_path.read_text()
        assert "test message 123" in content

    def test_idempotent(self, tmp_path: Path) -> None:
        _reset_logging()
        setup_logging(tmp_path / "a.log")
        setup_logging(tmp_path / "b.log")

        file_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1

    def test_file_log_level_override(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        setup_logging(log_path, file_log_level="WARNING")

        file_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.WARNING

    def test_console_log_level_override(self) -> None:
        _reset_logging()
        setup_logging(console_log_level="INFO")

        console_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.INFO

    def test_log_level_from_env_var(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        with patch.dict("os.environ", {"LOG_LEVEL": "ERROR"}):
            setup_logging(log_path)

        file_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.ERROR

    def test_cli_log_level_overrides_env(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        with patch.dict("os.environ", {"LOG_LEVEL": "ERROR"}):
            setup_logging(log_path, file_log_level="INFO")

        file_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.INFO

    def test_invalid_log_level_raises(self, tmp_path: Path) -> None:
        _reset_logging()
        with pytest.raises(ValueError, match="Invalid log level"):
            setup_logging(
                tmp_path / "test.log", file_log_level="NONEXISTENT"
            )

    def test_file_handler_respects_level(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        setup_logging(log_path, file_log_level="WARNING")

        test_logger = logging.getLogger("test.level_check")
        test_logger.debug("should not appear")
        test_logger.warning("should appear")

        content = log_path.read_text()
        assert "should not appear" not in content
        assert "should appear" in content

    def test_console_log_level_from_env_var(self) -> None:
        _reset_logging()
        with patch.dict("os.environ", {"CONSOLE_LOG_LEVEL": "INFO"}):
            setup_logging()

        console_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.INFO

    def test_cli_console_log_level_overrides_env(self) -> None:
        _reset_logging()
        with patch.dict("os.environ", {"CONSOLE_LOG_LEVEL": "ERROR"}):
            setup_logging(console_log_level="DEBUG")

        console_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.DEBUG

    def test_log_level_env_does_not_affect_console(self) -> None:
        _reset_logging()
        with patch.dict("os.environ", {"LOG_LEVEL": "DEBUG"}):
            setup_logging()

        console_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.CRITICAL

    def test_console_log_level_env_does_not_affect_file(
        self, tmp_path: Path
    ) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        with patch.dict("os.environ", {"CONSOLE_LOG_LEVEL": "DEBUG"}):
            setup_logging(log_path)

        file_handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.DEBUG

    def test_invalid_console_log_level_raises(self) -> None:
        _reset_logging()
        with pytest.raises(ValueError, match="Invalid log level"):
            setup_logging(console_log_level="NONEXISTENT")

    def test_httpcore_loggers_set_to_warning(self) -> None:
        _reset_logging()
        setup_logging()

        for name in _THIRD_PARTY_LOGGERS:
            assert logging.getLogger(name).level == logging.WARNING

    def test_httpcore_debug_logs_suppressed(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        setup_logging(log_path)

        httpcore_logger = logging.getLogger("httpcore.http11")
        httpcore_logger.debug("send request headers")
        httpcore_logger.debug("receive response headers")

        content = log_path.read_text()
        assert "send request headers" not in content
        assert "receive response headers" not in content

    def test_httpcore_warning_logs_not_suppressed(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        setup_logging(log_path)

        httpcore_logger = logging.getLogger("httpcore.connection")
        httpcore_logger.warning("connection pool is full")

        content = log_path.read_text()
        assert "connection pool is full" in content

    def test_httpx_logger_suppressed(self, tmp_path: Path) -> None:
        _reset_logging()
        log_path = tmp_path / "test.log"
        setup_logging(log_path)

        httpx_logger = logging.getLogger("httpx")
        httpx_logger.debug("HTTP request")

        content = log_path.read_text()
        assert "HTTP request" not in content
