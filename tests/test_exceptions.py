from garmin2fittrackee import ArchiveError, Garmin2FittrackeeError


class TestExceptions:
    def test_archive_error_is_garmin_error(self) -> None:
        assert issubclass(ArchiveError, Garmin2FittrackeeError)

    def test_archive_error_message(self) -> None:
        err = ArchiveError("test message")
        assert str(err) == "test message"

    def test_base_error_is_exception(self) -> None:
        assert issubclass(Garmin2FittrackeeError, Exception)
