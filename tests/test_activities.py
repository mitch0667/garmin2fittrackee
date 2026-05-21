import json
import logging
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from garmin2fittrackee import ActivityError
from garmin2fittrackee.garmin.activities import (
    FIT_EPOCH,
    GarminActivity,
    GarminActivityType,
    _check_fit_for_gps,
    _extract_activity_files_from_zips,
    _extract_fit_start_time,
    _extract_tcx_start_time,
    _fit_crc16,
    _parse_fit_file_id,
    build_uploaded_files_table,
    find_activity_files,
    find_matching_file,
    has_gps_data,
    parse_all_activities,
    parse_summarized_activities_file,
    patch_fit_product,
    patch_gpx_creator,
    patch_tcx_creator,
)


def _make_activity(
    activity_id: int = 123,
    type_key: str = "running",
    start_local: str = "2024-01-15 08:00:00",
    start_gmt: str = "2024-01-15 07:00:00",
    duration: float = 1800.0,
    distance: float = 5000.0,
    elevation_gain: float = 100.0,
    elevation_loss: float = 80.0,
    title: str | None = None,
    **extra: object,
) -> dict:
    data = {
        "activityId": activity_id,
        "activityType": {"typeKey": type_key},
        "startTimeLocal": start_local,
        "startTimeGMT": start_gmt,
        "durationInSeconds": duration,
        "distanceInMeters": distance,
        "elevationGainInMeters": elevation_gain,
        "elevationLossInMeters": elevation_loss,
        "averageSpeedInMetersPerSecond": 2.78,
        "maxSpeedInMetersPerSecond": 4.0,
        "totalCalories": 300.0,
    }
    if title is not None:
        data["title"] = title
    data.update(extra)
    return data


def _build_fit_file_id_bytes(
    file_type: int = 4,
    time_created: datetime | None = None,
    include_time: bool = True,
    header_size: int = 14,
    first_global_msg: int = 0,
) -> bytes:
    if time_created is None:
        time_created = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
    ts = int((time_created - FIT_EPOCH).total_seconds())
    header = bytearray(header_size)
    header[0] = header_size
    header[1] = 16
    struct.pack_into("<H", header, 2, 0)
    header[8:12] = b".FIT"
    if header_size >= 14:
        struct.pack_into("<H", header, 12, 0)
    records = bytearray()
    def_rec = bytearray()
    def_rec.append(0x40)
    def_rec.append(0)
    def_rec.append(0)
    def_rec.extend(struct.pack("<H", first_global_msg))
    fields = [(0, 1)]
    if include_time:
        fields.append((4, 4))
    def_rec.append(len(fields))
    for fnum, fsize in fields:
        def_rec.append(fnum)
        def_rec.append(fsize)
        def_rec.append(0x86 if fsize == 4 else 0x00)
    records.extend(def_rec)
    data_rec = bytearray()
    data_rec.append(0x00)
    for fnum, fsize in fields:
        if fnum == 0:
            data_rec.append(file_type)
        elif fnum == 4:
            data_rec.extend(struct.pack("<I", ts))
    records.extend(data_rec)
    struct.pack_into("<I", header, 4, len(records))
    return bytes(header) + bytes(records) + b"\x00\x00"


class TestGarminActivityModel:
    def test_basic_parsing(self) -> None:
        a = GarminActivity.model_validate(_make_activity())
        assert a.activity_id == 123
        assert a.activity_type_key == "running"
        assert a.start_time_local == "2024-01-15 08:00:00"
        assert a.duration_seconds == 1800
        assert a.distance_km == 5.0

    def test_start_datetime(self) -> None:
        a = GarminActivity.model_validate(_make_activity())
        dt = a.start_datetime
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 7
        assert dt.tzinfo is not None

    def test_elevation(self) -> None:
        a = GarminActivity.model_validate(_make_activity())
        assert a.elevation_gain == 100.0
        assert a.elevation_loss == 80.0

    def test_title(self) -> None:
        a = GarminActivity.model_validate(_make_activity(title="Morning Run"))
        assert a.title == "Morning Run"

    def test_title_none(self) -> None:
        a = GarminActivity.model_validate(_make_activity())
        assert a.title is None

    def test_extra_fields_ignored(self) -> None:
        data = _make_activity(unknownField="value")
        a = GarminActivity.model_validate(data)
        assert a.activity_id == 123


class TestGarminActivityNewExportFormat:
    def _make_new_format_activity(
        self,
        activity_id: int = 123,
        activity_type: str = "trail_running",
        start_time_local_ms: float = 1705305600000.0,
        start_time_gmt_ms: float = 1705302000000.0,
        duration_ms: float = 1800000.0,
        distance_cm: float = 500000.0,
        elevation_gain_cm: float = 10000.0,
        elevation_loss_cm: float = 8000.0,
        avg_speed: float = 0.278,
        max_speed: float = 0.4,
        calories: float = 300.0,
        name: str | None = None,
    ) -> dict:
        data: dict = {
            "activityId": activity_id,
            "activityType": activity_type,
            "startTimeLocal": start_time_local_ms,
            "startTimeGmt": start_time_gmt_ms,
            "duration": duration_ms,
            "distance": distance_cm,
            "elevationGain": elevation_gain_cm,
            "elevationLoss": elevation_loss_cm,
            "avgSpeed": avg_speed,
            "maxSpeed": max_speed,
            "calories": calories,
        }
        if name is not None:
            data["name"] = name
        return data

    def test_basic_parsing(self) -> None:
        a = GarminActivity.model_validate(self._make_new_format_activity())
        assert a.activity_id == 123
        assert a.activity_type_key == "trail_running"
        assert a.duration_seconds == 1800
        assert a.distance_km == 5.0
        assert a.elevation_gain_m == 100.0
        assert a.elevation_loss_m == 80.0

    def test_timestamp_conversion(self) -> None:
        a = GarminActivity.model_validate(self._make_new_format_activity())
        assert a.start_time_local == "2024-01-15 08:00:00"

    def test_string_activity_type(self) -> None:
        a = GarminActivity.model_validate(
            self._make_new_format_activity(activity_type="cycling")
        )
        assert a.activity_type_key == "cycling"

    def test_name_mapped_to_title(self) -> None:
        a = GarminActivity.model_validate(
            self._make_new_format_activity(name="Morning Run")
        )
        assert a.title == "Morning Run"

    def test_speed_conversion(self) -> None:
        a = GarminActivity.model_validate(self._make_new_format_activity())
        assert a.average_speed == pytest.approx(2.78, abs=0.01)
        assert a.max_speed == pytest.approx(4.0, abs=0.01)

    def test_old_format_still_works(self) -> None:
        a = GarminActivity.model_validate(_make_activity())
        assert a.activity_id == 123
        assert a.duration_seconds == 1800
        assert a.distance_km == 5.0


class TestGarminActivityType:
    def test_type_key(self) -> None:
        t = GarminActivityType.model_validate({"typeKey": "cycling"})
        assert t.type_key == "cycling"


class TestFindActivityFiles:
    def test_finds_activity_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "2024_summarizedActivities.json"
        f1.write_text("[]")
        f2 = tmp_path / "2023_summarizedActivities.json"
        f2.write_text("[]")
        other = tmp_path / "other.json"
        other.write_text("{}")

        files = find_activity_files(tmp_path)
        assert len(files) == 2

    def test_finds_no_files(self, tmp_path: Path) -> None:
        files = find_activity_files(tmp_path)
        assert files == []

    def test_finds_nested_files(self, tmp_path: Path) -> None:
        sub = tmp_path / "DI_CONNECT" / "DI-Connect-Fitness-Statistics"
        sub.mkdir(parents=True)
        f = sub / "2024_summarizedActivities.json"
        f.write_text("[]")

        files = find_activity_files(tmp_path)
        assert len(files) == 1


class TestParseSummarizedActivitiesFile:
    def test_parse_list(self, tmp_path: Path) -> None:
        data = [_make_activity(), _make_activity(activity_id=456, type_key="cycling")]
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text(json.dumps(data))

        activities = parse_summarized_activities_file(f)
        assert len(activities) == 2
        assert activities[0].activity_id == 123
        assert activities[1].activity_id == 456

    def test_parse_wrapped_dict(self, tmp_path: Path) -> None:
        data = {"summarizedActivities": [_make_activity()]}
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text(json.dumps(data))

        activities = parse_summarized_activities_file(f)
        assert len(activities) == 1

    def test_parse_activities_key(self, tmp_path: Path) -> None:
        data = {"activities": [_make_activity()]}
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text(json.dumps(data))

        activities = parse_summarized_activities_file(f)
        assert len(activities) == 1

    def test_parse_data_key(self, tmp_path: Path) -> None:
        data = {"data": [_make_activity()]}
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text(json.dumps(data))

        activities = parse_summarized_activities_file(f)
        assert len(activities) == 1

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ActivityError, match="Activity file not found"):
            parse_summarized_activities_file(tmp_path / "missing.json")

    def test_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad_summarizedActivities.json"
        f.write_text("not json")
        with pytest.raises(ActivityError, match="Invalid JSON"):
            parse_summarized_activities_file(f)

    def test_unexpected_structure(self, tmp_path: Path) -> None:
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text('{"other": "data"}')
        with pytest.raises(ActivityError, match="Unexpected activity data"):
            parse_summarized_activities_file(f)

    def test_skips_invalid_entries(self, tmp_path: Path) -> None:
        data = [_make_activity(), {"invalid": True}, "not a dict"]
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text(json.dumps(data))

        activities = parse_summarized_activities_file(f)
        assert len(activities) == 1

    def test_parse_summarized_activities_export_list(
        self, tmp_path: Path
    ) -> None:
        data = [{"summarizedActivitiesExport": [_make_activity()]}]
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text(json.dumps(data))

        activities = parse_summarized_activities_file(f)
        assert len(activities) == 1
        assert activities[0].activity_id == 123

    def test_parse_summarized_activities_export_dict(
        self, tmp_path: Path
    ) -> None:
        data = {"summarizedActivitiesExport": [_make_activity()]}
        f = tmp_path / "test_summarizedActivities.json"
        f.write_text(json.dumps(data))

        activities = parse_summarized_activities_file(f)
        assert len(activities) == 1


class TestParseAllActivities:
    def test_parse_multiple_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "2024_summarizedActivities.json"
        f1.write_text(json.dumps([_make_activity()]))
        f2 = tmp_path / "2023_summarizedActivities.json"
        f2.write_text(json.dumps([_make_activity(activity_id=456)]))

        activities = parse_all_activities(tmp_path)
        assert len(activities) == 2

    def test_no_files_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ActivityError, match="No activity files found"):
            parse_all_activities(tmp_path)


class TestParseFitFileId:
    def test_valid_activity_with_time(self) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        data = _build_fit_file_id_bytes(file_type=4, time_created=dt)
        result = _parse_fit_file_id(data)
        assert result is not None
        assert result[0] == 4
        assert result[1] is not None
        assert result[1] == dt

    def test_valid_activity_without_time(self) -> None:
        data = _build_fit_file_id_bytes(file_type=4, include_time=False)
        result = _parse_fit_file_id(data)
        assert result is not None
        assert result[0] == 4
        assert result[1] is None

    def test_non_activity_type(self) -> None:
        data = _build_fit_file_id_bytes(file_type=2)
        result = _parse_fit_file_id(data)
        assert result is not None
        assert result[0] == 2

    def test_too_short(self) -> None:
        assert _parse_fit_file_id(b"\x00" * 10) is None

    def test_invalid_magic(self) -> None:
        data = bytearray(14)
        data[0] = 14
        data[8:12] = b"NOPE"
        assert _parse_fit_file_id(bytes(data)) is None

    def test_invalid_header_size(self) -> None:
        data = bytearray(14)
        data[0] = 20
        data[8:12] = b".FIT"
        assert _parse_fit_file_id(bytes(data)) is None

    def test_non_file_id_first_message(self) -> None:
        data = _build_fit_file_id_bytes(first_global_msg=20)
        result = _parse_fit_file_id(data)
        assert result is None

    def test_data_record_instead_of_definition(self) -> None:
        header = bytearray(14)
        header[0] = 14
        header[1] = 16
        header[8:12] = b".FIT"
        records = bytearray()
        records.append(0x00)
        records.append(0)
        struct.pack_into("<I", header, 4, len(records))
        data = bytes(header) + bytes(records) + b"\x00\x00"
        assert _parse_fit_file_id(data) is None

    def test_12_byte_header(self) -> None:
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        data = _build_fit_file_id_bytes(
            file_type=4, time_created=dt, header_size=12
        )
        result = _parse_fit_file_id(data)
        assert result is not None
        assert result[0] == 4
        assert result[1] == dt

    def test_compressed_timestamp_header_rejected(self) -> None:
        header = bytearray(14)
        header[0] = 14
        header[1] = 16
        header[8:12] = b".FIT"
        records = bytearray()
        records.append(0x80)
        struct.pack_into("<I", header, 4, len(records))
        data = bytes(header) + bytes(records) + b"\x00\x00"
        assert _parse_fit_file_id(data) is None


class TestExtractFitStartTime:
    def test_valid_fit_file(self, tmp_path: Path) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        data = _build_fit_file_id_bytes(time_created=dt)
        fit_path = tmp_path / "test.fit"
        fit_path.write_bytes(data)
        result = _extract_fit_start_time(fit_path)
        assert result == dt

    def test_fit_without_time_created(self, tmp_path: Path) -> None:
        data = _build_fit_file_id_bytes(include_time=False)
        fit_path = tmp_path / "notime.fit"
        fit_path.write_bytes(data)
        result = _extract_fit_start_time(fit_path)
        assert result is None

    def test_invalid_fit_file(self, tmp_path: Path) -> None:
        fit_path = tmp_path / "bad.fit"
        fit_path.write_bytes(b"\x00" * 20)
        result = _extract_fit_start_time(fit_path)
        assert result is None

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        fit_path = tmp_path / "missing.fit"
        result = _extract_fit_start_time(fit_path)
        assert result is None


class TestBuildUploadedFilesTable:
    def test_no_uploaded_dir(self, tmp_path: Path) -> None:
        table = build_uploaded_files_table(tmp_path)
        assert table == {}

    def test_with_gpx_file(self, tmp_path: Path) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)

        gpx_content = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <name>Test</name>
    <trkseg>
      <trkpt lat="48.8566" lon="2.3522">
        <time>2024-01-15T08:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""
        gpx_file = uploaded / "test.gpx"
        gpx_file.write_text(gpx_content)

        table = build_uploaded_files_table(tmp_path)
        assert len(table) == 1
        start_time = list(table.keys())[0]
        assert start_time.year == 2024
        assert start_time.month == 1

    def test_empty_gpx_skipped(self, tmp_path: Path) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)
        gpx_file = uploaded / "empty.gpx"
        gpx_file.write_text("<gpx></gpx>")

        table = build_uploaded_files_table(tmp_path)
        assert table == {}

    def test_with_fit_file(self, tmp_path: Path) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        fit_data = _build_fit_file_id_bytes(time_created=dt)
        fit_file = uploaded / "test.fit"
        fit_file.write_bytes(fit_data)
        table = build_uploaded_files_table(tmp_path)
        assert len(table) == 1
        start_time = list(table.keys())[0]
        assert start_time == dt

    def test_fit_file_without_time_skipped(self, tmp_path: Path) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)
        fit_data = _build_fit_file_id_bytes(include_time=False)
        fit_file = uploaded / "notime.fit"
        fit_file.write_bytes(fit_data)
        table = build_uploaded_files_table(tmp_path)
        assert table == {}

    def test_with_tcx_file(self, tmp_path: Path) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)
        tcx_content = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2024-03-10T14:30:00.000Z</Id>
      <Lap StartTime="2024-03-10T14:30:00.000Z">
        <Track>
          <Trackpoint>
            <Time>2024-03-10T14:30:00.000Z</Time>
            <Position>
              <LatitudeDegrees>48.8566</LatitudeDegrees>
              <LongitudeDegrees>2.3522</LongitudeDegrees>
            </Position>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        tcx_file = uploaded / "run.tcx"
        tcx_file.write_text(tcx_content)

        table = build_uploaded_files_table(tmp_path)
        assert len(table) == 1
        start_time = list(table.keys())[0]
        assert start_time.year == 2024
        assert start_time.month == 3
        assert start_time.day == 10
        assert start_time.hour == 14
        assert start_time.minute == 30

    def test_tcx_without_id_skipped(self, tmp_path: Path) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)
        tcx_content = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Lap>
        <Track></Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        tcx_file = uploaded / "empty.tcx"
        tcx_file.write_text(tcx_content)

        table = build_uploaded_files_table(tmp_path)
        assert table == {}

    def test_mixed_gpx_fit_tcx(self, tmp_path: Path) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)

        gpx_content = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="48.8566" lon="2.3522">
        <time>2024-01-15T08:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""
        (uploaded / "test.gpx").write_text(gpx_content)

        fit_dt = datetime(2024, 2, 20, 10, 0, 0, tzinfo=timezone.utc)
        fit_data = _build_fit_file_id_bytes(time_created=fit_dt)
        (uploaded / "test.fit").write_bytes(fit_data)

        tcx_content = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2024-03-10T14:30:00.000Z</Id>
      <Lap StartTime="2024-03-10T14:30:00.000Z">
        <Track>
          <Trackpoint>
            <Time>2024-03-10T14:30:00.000Z</Time>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        (uploaded / "run.tcx").write_text(tcx_content)

        table = build_uploaded_files_table(tmp_path)
        assert len(table) == 3

    def test_multiple_files_same_timestamp_keeps_largest(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)

        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)

        gpx_content = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="48.8566" lon="2.3522">
        <time>2024-01-15T08:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""
        gpx_file = uploaded / "test.gpx"
        gpx_file.write_text(gpx_content)

        fit_data = _build_fit_file_id_bytes(time_created=dt)
        fit_file = uploaded / "test.fit"
        fit_file.write_bytes(fit_data + b"\x00" * 500)

        with caplog.at_level(logging.WARNING):
            table = build_uploaded_files_table(tmp_path)

        assert len(table) == 1
        kept_path = list(table.values())[0]
        assert kept_path == fit_file
        assert "[MULTI-MATCH]" in caplog.text
        assert "test.fit" in caplog.text
        assert "test.gpx" in caplog.text

    def test_multiple_files_same_timestamp_no_warning_for_single(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        uploaded = tmp_path / "DI_CONNECT" / "DI-Connect-Uploaded-Files"
        uploaded.mkdir(parents=True)

        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        fit_data = _build_fit_file_id_bytes(time_created=dt)
        fit_file = uploaded / "test.fit"
        fit_file.write_bytes(fit_data)

        with caplog.at_level(logging.WARNING):
            table = build_uploaded_files_table(tmp_path)

        assert len(table) == 1
        assert "[MULTI-MATCH]" not in caplog.text


class TestExtractTcxStartTime:
    def test_extracts_from_id(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2024-03-10T14:30:00.000Z</Id>
      <Lap StartTime="2024-03-10T14:30:00.000Z">
        <Track></Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        p = tmp_path / "test.tcx"
        p.write_text(tcx)
        result = _extract_tcx_start_time(p)
        assert result is not None
        assert result.year == 2024
        assert result.month == 3
        assert result.hour == 14
        assert result.minute == 30

    def test_falls_back_to_lap_starttime(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Lap StartTime="2024-06-01T09:15:00.000Z">
        <Track></Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        p = tmp_path / "test.tcx"
        p.write_text(tcx)
        result = _extract_tcx_start_time(p)
        assert result is not None
        assert result.month == 6
        assert result.hour == 9
        assert result.minute == 15

    def test_no_time_returns_none(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Lap>
        <Track></Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        p = tmp_path / "test.tcx"
        p.write_text(tcx)
        assert _extract_tcx_start_time(p) is None

    def test_invalid_xml_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.tcx"
        p.write_text("not xml")
        assert _extract_tcx_start_time(p) is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.tcx"
        p.write_text("")
        assert _extract_tcx_start_time(p) is None


class TestFindMatchingFile:
    def test_exact_match(self) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        path = Path("/tmp/test.gpx")
        table = {dt: path}

        result = find_matching_file(dt, table)
        assert result == path

    def test_within_margin(self) -> None:
        dt1 = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        dt2 = datetime(2024, 1, 15, 8, 0, 5, tzinfo=timezone.utc)
        path = Path("/tmp/test.gpx")
        table = {dt2: path}

        result = find_matching_file(dt1, table, margin_seconds=10)
        assert result == path

    def test_outside_margin(self) -> None:
        dt1 = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        dt2 = datetime(2024, 1, 15, 8, 0, 20, tzinfo=timezone.utc)
        path = Path("/tmp/test.gpx")
        table = {dt2: path}

        result = find_matching_file(dt1, table, margin_seconds=10)
        assert result is None

    def test_empty_table(self) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        result = find_matching_file(dt, {})
        assert result is None

    def test_multiple_matches_keeps_largest(self, tmp_path: Path) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        small = tmp_path / "small.fit"
        small.write_bytes(b"\x00" * 100)
        large = tmp_path / "large.gpx"
        large.write_bytes(b"\x00" * 500)

        dt2 = datetime(2024, 1, 15, 8, 0, 5, tzinfo=timezone.utc)
        table = {dt: small, dt2: large}

        result = find_matching_file(dt, table, margin_seconds=10)
        assert result == large

    def test_multiple_matches_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        small = tmp_path / "small.fit"
        small.write_bytes(b"\x00" * 100)
        large = tmp_path / "large.gpx"
        large.write_bytes(b"\x00" * 500)

        dt2 = datetime(2024, 1, 15, 8, 0, 5, tzinfo=timezone.utc)
        table = {dt: small, dt2: large}

        with caplog.at_level(logging.WARNING):
            find_matching_file(
                dt, table, margin_seconds=10, activity_name="Morning Run"
            )

        assert "[MULTI-MATCH]" in caplog.text
        assert "Morning Run" in caplog.text
        assert "large.gpx" in caplog.text
        assert "small.fit" in caplog.text

    def test_single_match_no_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        path = tmp_path / "test.gpx"
        path.write_bytes(b"\x00" * 100)

        table = {dt: path}
        with caplog.at_level(logging.WARNING):
            find_matching_file(dt, table)

        assert "[MULTI-MATCH]" not in caplog.text


class TestExtractActivityFilesFromZips:
    def test_extracts_activity_fit_from_zip(self, tmp_path: Path) -> None:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        fit_data = _build_fit_file_id_bytes(
            file_type=4, time_created=dt
        )
        zip_path = tmp_path / "upload.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("activity.fit", fit_data)
        result = _extract_activity_files_from_zips(tmp_path)
        assert len(result) == 1
        assert result[0].name == "activity.fit"

    def test_skips_non_activity_fit(self, tmp_path: Path) -> None:
        fit_data = _build_fit_file_id_bytes(file_type=2)
        zip_path = tmp_path / "upload.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("settings.fit", fit_data)
        result = _extract_activity_files_from_zips(tmp_path)
        assert result == []

    def test_skips_non_fit_in_zip(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "upload.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.json", b'{"key": "value"}')
        result = _extract_activity_files_from_zips(tmp_path)
        assert result == []

    def test_skips_invalid_fit_in_zip(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "upload.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("bad.fit", b"\x00" * 20)
        result = _extract_activity_files_from_zips(tmp_path)
        assert result == []

    def test_multiple_zips(self, tmp_path: Path) -> None:
        dt1 = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        dt2 = datetime(2024, 2, 20, 10, 0, 0, tzinfo=timezone.utc)
        fit1 = _build_fit_file_id_bytes(file_type=4, time_created=dt1)
        fit2 = _build_fit_file_id_bytes(file_type=4, time_created=dt2)
        zip1 = tmp_path / "upload1.zip"
        with zipfile.ZipFile(zip1, "w") as zf:
            zf.writestr("a.fit", fit1)
        zip2 = tmp_path / "upload2.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("b.fit", fit2)
        result = _extract_activity_files_from_zips(tmp_path)
        assert len(result) == 2

    def test_no_zip_files(self, tmp_path: Path) -> None:
        result = _extract_activity_files_from_zips(tmp_path)
        assert result == []


def _build_minimal_fit(
    global_msg: int = 20,
    include_position: bool = True,
    position_lat: int = 600000000,
    position_lon: int = 200000000,
    extra_fields: list[tuple[int, int, bytes]] | None = None,
) -> bytes:
    header = bytearray(14)
    header[0] = 14
    header[1] = 16
    struct.pack_into("<H", header, 2, 0)
    header[8:12] = b".FIT"
    struct.pack_into("<H", header, 12, 0)

    records = bytearray()

    def_hdr = bytearray()
    def_hdr.append(0x40)
    def_hdr.append(0)
    def_hdr.append(0)
    def_hdr.extend(struct.pack("<H", global_msg))

    fields = []
    if global_msg == 20:
        if include_position:
            fields.append((0, 4))
            fields.append((1, 4))
        if extra_fields:
            fields.extend(extra_fields)
        if not fields:
            fields.append((253, 4))
    else:
        if extra_fields:
            fields.extend(extra_fields)
        else:
            fields.append((253, 4))

    def_hdr.append(len(fields))
    for fnum, fsize in fields:
        def_hdr.append(fnum)
        def_hdr.append(fsize)
        def_hdr.append(0x86 if fsize == 4 else 0x00)
    records.extend(def_hdr)

    data_rec = bytearray()
    data_rec.append(0x00)
    if global_msg == 20 and include_position:
        data_rec.extend(struct.pack("<i", position_lat))
        data_rec.extend(struct.pack("<i", position_lon))
        if extra_fields:
            for _, fsize, fval in extra_fields:
                padded = fval[:fsize].ljust(fsize, b"\x00")
                data_rec.extend(padded)
    elif global_msg == 20 and not include_position:
        if extra_fields:
            for _, fsize, fval in extra_fields:
                padded = fval[:fsize].ljust(fsize, b"\x00")
                data_rec.extend(padded)
        else:
            data_rec.extend(struct.pack("<I", 0))
    else:
        if extra_fields:
            for _, fsize, fval in extra_fields:
                padded = fval[:fsize].ljust(fsize, b"\x00")
                data_rec.extend(padded)
        else:
            data_rec.extend(struct.pack("<I", 0))
    records.extend(data_rec)

    struct.pack_into("<I", header, 4, len(records))
    return bytes(header) + bytes(records) + b"\x00\x00"


class TestCheckFitForGps:
    def test_fit_with_gps_data(self) -> None:
        data = _build_minimal_fit(include_position=True)
        assert _check_fit_for_gps(data) is True

    def test_fit_without_gps_data(self) -> None:
        data = _build_minimal_fit(include_position=False)
        assert _check_fit_for_gps(data) is False

    def test_fit_with_zero_position(self) -> None:
        data = _build_minimal_fit(
            include_position=True, position_lat=0, position_lon=0
        )
        assert _check_fit_for_gps(data) is False

    def test_fit_with_invalid_position(self) -> None:
        data = _build_minimal_fit(
            include_position=True,
            position_lat=0x7FFFFFFF,
            position_lon=0x7FFFFFFF,
        )
        assert _check_fit_for_gps(data) is False

    def test_fit_non_record_message(self) -> None:
        data = _build_minimal_fit(global_msg=0, include_position=False)
        assert _check_fit_for_gps(data) is False

    def test_fit_too_short(self) -> None:
        assert _check_fit_for_gps(b"\x00\x00") is False

    def test_fit_invalid_magic(self) -> None:
        data = bytearray(14)
        data[0] = 14
        data[8:12] = b"NOPE"
        assert _check_fit_for_gps(bytes(data)) is False


class TestHasGpsData:
    def test_gpx_with_gps(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="48.8566" lon="2.3522">
        <time>2024-01-15T08:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""
        p = tmp_path / "test.gpx"
        p.write_text(gpx)
        assert has_gps_data(p) is True

    def test_gpx_without_gps(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="0.0" lon="0.0">
        <time>2024-01-15T08:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""
        p = tmp_path / "test.gpx"
        p.write_text(gpx)
        assert has_gps_data(p) is False

    def test_gpx_empty_track(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg></trkseg>
  </trk>
</gpx>"""
        p = tmp_path / "test.gpx"
        p.write_text(gpx)
        assert has_gps_data(p) is False

    def test_fit_with_gps(self, tmp_path: Path) -> None:
        data = _build_minimal_fit(include_position=True)
        p = tmp_path / "test.fit"
        p.write_bytes(data)
        assert has_gps_data(p) is True

    def test_fit_without_gps(self, tmp_path: Path) -> None:
        data = _build_minimal_fit(include_position=False)
        p = tmp_path / "test.fit"
        p.write_bytes(data)
        assert has_gps_data(p) is False

    def test_tcx_with_gps(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity>
      <Lap>
        <Track>
          <Trackpoint>
            <Position>
              <LatitudeDegrees>48.8566</LatitudeDegrees>
              <LongitudeDegrees>2.3522</LongitudeDegrees>
            </Position>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        p = tmp_path / "test.tcx"
        p.write_text(tcx)
        assert has_gps_data(p) is True

    def test_tcx_without_gps(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity>
      <Lap>
        <Track>
          <Trackpoint>
            <Time>2024-01-15T08:00:00Z</Time>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        p = tmp_path / "test.tcx"
        p.write_text(tcx)
        assert has_gps_data(p) is False

    def test_unknown_extension_returns_true(self, tmp_path: Path) -> None:
        p = tmp_path / "test.xyz"
        p.write_text("whatever")
        assert has_gps_data(p) is True


class TestDeviceProductName:
    def test_device_product_name_parsed(self) -> None:
        data = _make_activity(deviceProductName="Garmin fenix 7")
        a = GarminActivity.model_validate(data)
        assert a.device_product_name == "Garmin fenix 7"

    def test_device_product_name_none_by_default(self) -> None:
        data = _make_activity()
        a = GarminActivity.model_validate(data)
        assert a.device_product_name is None

    def test_new_format_with_device_product_name(self) -> None:
        data = {
            "activityId": 123,
            "activityType": "running",
            "startTimeLocal": 1705305600000.0,
            "startTimeGmt": 1705302000000.0,
            "duration": 1800000.0,
            "distance": 500000.0,
            "deviceProductName": "Forerunner 265",
        }
        a = GarminActivity.model_validate(data)
        assert a.device_product_name == "Forerunner 265"


class TestPatchGpxCreator:
    def test_patches_creator(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="old_device">
  <trk><trkseg>
    <trkpt lat="48.8566" lon="2.3522"><time>2024-01-15T08:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "original.gpx"
        gpx_path.write_text(gpx)

        out = patch_gpx_creator(gpx_path, "Garmin fenix 7", tmp_path / "out")
        content = out.read_text()
        assert 'creator="Garmin fenix 7"' in content
        assert "old_device" not in content

    def test_output_file_same_name(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"><trk></trk></gpx>"""
        gpx_path = tmp_path / "run.gpx"
        gpx_path.write_text(gpx)

        out = patch_gpx_creator(gpx_path, "New Device", tmp_path / "out")
        assert out.name == "run.gpx"

    def test_does_not_modify_original(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="original"><trk></trk></gpx>"""
        gpx_path = tmp_path / "original.gpx"
        gpx_path.write_text(gpx)
        original_content = gpx_path.read_text()

        patch_gpx_creator(gpx_path, "New Device", tmp_path / "out")
        assert gpx_path.read_text() == original_content


class TestPatchTcxCreator:
    def test_patches_creator_name(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2024-03-10T14:30:00.000Z</Id>
      <Creator>
        <Name>Wrong Device</Name>
      </Creator>
      <Lap StartTime="2024-03-10T14:30:00.000Z">
        <Track>
          <Trackpoint>
            <Time>2024-03-10T14:30:00.000Z</Time>
            <Position>
              <LatitudeDegrees>48.8566</LatitudeDegrees>
              <LongitudeDegrees>2.3522</LongitudeDegrees>
            </Position>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        tcx_path = tmp_path / "run.tcx"
        tcx_path.write_text(tcx)

        out = patch_tcx_creator(tcx_path, "Garmin fenix 7", tmp_path / "out")
        content = out.read_text()
        assert "Garmin fenix 7" in content
        assert "Wrong Device" not in content

    def test_does_not_modify_original(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Creator><Name>Original</Name></Creator>
      <Lap><Track></Track></Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        tcx_path = tmp_path / "run.tcx"
        tcx_path.write_text(tcx)
        original = tcx_path.read_text()

        patch_tcx_creator(tcx_path, "New Device", tmp_path / "out")
        assert tcx_path.read_text() == original

    def test_output_file_same_name(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Creator><Name>Test</Name></Creator>
      <Lap><Track></Track></Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        tcx_path = tmp_path / "run.tcx"
        tcx_path.write_text(tcx)

        out = patch_tcx_creator(tcx_path, "New", tmp_path / "out")
        assert out.name == "run.tcx"


def _build_fit_with_product_id(
    file_type: int = 4,
    product_id: int = 3906,
    manufacturer: int = 1,
    include_time: bool = True,
    header_size: int = 14,
) -> bytes:
    if header_size == 14:
        header = bytearray(14)
        header[0] = 14
        header[1] = 16
        struct.pack_into("<H", header, 2, 0)
        header[8:12] = b".FIT"
        struct.pack_into("<H", header, 12, 0)
    else:
        header = bytearray(12)
        header[0] = 12
        header[1] = 16
        struct.pack_into("<H", header, 2, 0)
        header[8:12] = b".FIT"

    records = bytearray()

    def_rec = bytearray()
    def_rec.append(0x40)
    def_rec.append(0)
    def_rec.append(0)
    def_rec.extend(struct.pack("<H", 0))

    fields = [(0, 1), (1, 2), (2, 2)]
    if include_time:
        fields.append((4, 4))
    def_rec.append(len(fields))
    for fnum, fsize in fields:
        def_rec.append(fnum)
        def_rec.append(fsize)
        def_rec.append(0x86 if fsize >= 2 else 0x00)
    records.extend(def_rec)

    data_rec = bytearray()
    data_rec.append(0x00)
    data_rec.append(file_type)
    data_rec.extend(struct.pack("<H", manufacturer))
    data_rec.extend(struct.pack("<H", product_id))
    if include_time:
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        ts = int((dt - FIT_EPOCH).total_seconds())
        data_rec.extend(struct.pack("<I", ts))
    records.extend(data_rec)

    struct.pack_into("<I", header, 4, len(records))
    data = bytes(header) + bytes(records) + b"\x00\x00"
    crc = _fit_crc16(data[:-2])
    return data[:-2] + struct.pack("<H", crc)


class TestPatchFitProduct:
    def test_patches_product_id(self, tmp_path: Path) -> None:
        fit_data = _build_fit_with_product_id(product_id=3906)
        fit_path = tmp_path / "activity.fit"
        fit_path.write_bytes(fit_data)

        out = patch_fit_product(fit_path, 3113, tmp_path / "out")
        assert out is not None
        patched = out.read_bytes()
        result = _parse_fit_file_id(patched)
        assert result is not None

        assert result[0] == 4

        from src.garmin2fittrackee.garmin.activities import _find_product_field_offset
        offset_info = _find_product_field_offset(patched, patched[0])
        assert offset_info is not None
        actual_product = struct.unpack_from("<H", patched, offset_info[0])[0]
        assert actual_product == 3113

    def test_does_not_modify_original(self, tmp_path: Path) -> None:
        fit_data = _build_fit_with_product_id(product_id=3906)
        fit_path = tmp_path / "activity.fit"
        fit_path.write_bytes(fit_data)
        original = fit_path.read_bytes()

        patch_fit_product(fit_path, 3113, tmp_path / "out")
        assert fit_path.read_bytes() == original

    def test_output_file_same_name(self, tmp_path: Path) -> None:
        fit_data = _build_fit_with_product_id()
        fit_path = tmp_path / "run.fit"
        fit_path.write_bytes(fit_data)

        out = patch_fit_product(fit_path, 3113, tmp_path / "out")
        assert out is not None
        assert out.name == "run.fit"

    def test_returns_none_for_too_short(self, tmp_path: Path) -> None:
        fit_path = tmp_path / "short.fit"
        fit_path.write_bytes(b"\x00" * 10)

        result = patch_fit_product(fit_path, 3113, tmp_path / "out")
        assert result is None

    def test_returns_none_for_invalid_magic(self, tmp_path: Path) -> None:
        data = bytearray(20)
        data[0] = 14
        data[8:12] = b"NOPE"
        fit_path = tmp_path / "bad.fit"
        fit_path.write_bytes(bytes(data))

        result = patch_fit_product(fit_path, 3113, tmp_path / "out")
        assert result is None

    def test_crc_is_valid_after_patch(self, tmp_path: Path) -> None:
        fit_data = _build_fit_with_product_id(product_id=3906)
        fit_path = tmp_path / "activity.fit"
        fit_path.write_bytes(fit_data)

        out = patch_fit_product(fit_path, 3113, tmp_path / "out")
        assert out is not None
        patched = out.read_bytes()
        expected_crc = _fit_crc16(patched[:-2])
        actual_crc = struct.unpack_from("<H", patched, len(patched) - 2)[0]
        assert actual_crc == expected_crc

    def test_12_byte_header(self, tmp_path: Path) -> None:
        fit_data = _build_fit_with_product_id(
            product_id=3906, header_size=12
        )
        fit_path = tmp_path / "activity.fit"
        fit_path.write_bytes(fit_data)

        out = patch_fit_product(fit_path, 3113, tmp_path / "out")
        assert out is not None
        patched = out.read_bytes()
        expected_crc = _fit_crc16(patched[:-2])
        actual_crc = struct.unpack_from("<H", patched, len(patched) - 2)[0]
        assert actual_crc == expected_crc


class TestFitCrc16:
    def test_empty_data(self) -> None:
        assert _fit_crc16(b"") == 0

    def test_known_value(self) -> None:
        assert _fit_crc16(b"hello world") == 0x272D

    def test_deterministic(self) -> None:
        data = b"hello world"
        assert _fit_crc16(data) == _fit_crc16(data)
