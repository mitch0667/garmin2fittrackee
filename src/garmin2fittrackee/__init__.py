class Garmin2FittrackeeError(Exception):
    pass


class ArchiveError(Garmin2FittrackeeError):
    pass


class GearError(Garmin2FittrackeeError):
    pass


class ActivityError(Garmin2FittrackeeError):
    pass


class FitTrackeeError(Garmin2FittrackeeError):
    pass


class MappingError(Garmin2FittrackeeError):
    pass
