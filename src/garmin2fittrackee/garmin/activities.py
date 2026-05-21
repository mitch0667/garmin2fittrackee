import json
import logging
import struct
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from garmin2fittrackee import ActivityError

logger = logging.getLogger(__name__)

FIT_EPOCH = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
FIT_MAGIC = b".FIT"
FIT_FILE_TYPE_ACTIVITY = 4


class GarminActivityType(BaseModel):
    type_key: str = Field(alias="typeKey")

    model_config = {"populate_by_name": True}


class GarminActivity(BaseModel):
    activity_id: int = Field(alias="activityId")
    activity_type: GarminActivityType = Field(alias="activityType")
    start_time_local: str = Field(alias="startTimeLocal")
    start_time_gmt: str = Field(alias="startTimeGMT")
    durationInSeconds: float = 0.0
    distanceInMeters: float = 0.0
    elevation_gain: float = Field(default=0.0, alias="elevationGainInMeters")
    elevation_loss: float = Field(default=0.0, alias="elevationLossInMeters")
    average_speed: float = Field(default=0.0, alias="averageSpeedInMetersPerSecond")
    max_speed: float = Field(default=0.0, alias="maxSpeedInMetersPerSecond")
    calories: float = Field(default=0.0, alias="totalCalories")
    title: str | None = None
    steps: int = Field(default=0, alias="steps")
    device_product_name: str | None = Field(default=None, alias="deviceProductName")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _normalize_garmin_format(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        at = data.get("activityType")
        if isinstance(at, str):
            data["activityType"] = {"typeKey": at}

        for key in ("startTimeLocal", "startTimeGmt", "startTimeGMT"):
            v = data.get(key)
            if isinstance(v, (int, float)):
                ts = v / 1000 if v > 1e12 else v
                data[key] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

        if "startTimeGmt" in data and "startTimeGMT" not in data:
            data["startTimeGMT"] = data.pop("startTimeGmt")

        if "duration" in data and "durationInSeconds" not in data:
            data["durationInSeconds"] = data.pop("duration") / 1000

        if "distance" in data and "distanceInMeters" not in data:
            data["distanceInMeters"] = data.pop("distance") / 100

        if "elevationGain" in data and "elevationGainInMeters" not in data:
            data["elevationGainInMeters"] = data.pop("elevationGain") / 100

        if "elevationLoss" in data and "elevationLossInMeters" not in data:
            data["elevationLossInMeters"] = data.pop("elevationLoss") / 100

        if "avgSpeed" in data and "averageSpeedInMetersPerSecond" not in data:
            data["averageSpeedInMetersPerSecond"] = data.pop("avgSpeed") * 10

        if "maxSpeed" in data and "maxSpeedInMetersPerSecond" not in data:
            data["maxSpeedInMetersPerSecond"] = data.pop("maxSpeed") * 10

        if "calories" in data and "totalCalories" not in data:
            data["totalCalories"] = data.pop("calories")

        if "name" in data and "title" not in data:
            data["title"] = data.pop("name")

        return data

    @property
    def activity_type_key(self) -> str:
        return self.activity_type.type_key

    @property
    def start_datetime(self) -> datetime:
        return datetime.strptime(
            self.start_time_gmt, "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)

    @property
    def duration_seconds(self) -> int:
        return int(self.durationInSeconds)

    @property
    def distance_km(self) -> float:
        return round(self.distanceInMeters / 1000, 3)

    @property
    def elevation_gain_m(self) -> float:
        return round(self.elevation_gain, 1)

    @property
    def elevation_loss_m(self) -> float:
        return round(self.elevation_loss, 1)


def find_activity_files(extracted_dir: Path) -> list[Path]:
    files = sorted(extracted_dir.rglob("*_summarizedActivities.json"))
    logger.info("Found %d activity file(s) in %s", len(files), extracted_dir)
    return files


def parse_summarized_activities_file(path: Path) -> list[GarminActivity]:
    if not path.exists():
        raise ActivityError(f"Activity file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ActivityError(f"Invalid JSON in {path}: {exc}") from exc

    items: list[object] = []
    if isinstance(raw, list):
        if raw and isinstance(raw[0], dict):
            for key in (
                "summarizedActivitiesExport",
                "summarizedActivities",
                "activities",
                "data",
            ):
                if key in raw[0] and isinstance(raw[0][key], list):
                    items = raw[0][key]
                    break
            if not items:
                items = raw
        else:
            items = raw
    elif isinstance(raw, dict):
        for key in (
            "summarizedActivitiesExport",
            "summarizedActivities",
            "activities",
            "data",
        ):
            if key in raw and isinstance(raw[key], list):
                items = raw[key]
                break
        if not items:
            raise ActivityError(f"Unexpected activity data structure in {path}")

    activities: list[GarminActivity] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            activities.append(GarminActivity.model_validate(item))
        except Exception as exc:
            logger.warning("Skipping invalid activity entry: %s", exc)

    logger.info("Parsed %d activities from %s", len(activities), path)
    return activities


def parse_all_activities(extracted_dir: Path) -> list[GarminActivity]:
    files = find_activity_files(extracted_dir)
    if not files:
        raise ActivityError(
            f"No activity files found in {extracted_dir}"
        )

    all_activities: list[GarminActivity] = []
    for f in files:
        all_activities.extend(parse_summarized_activities_file(f))

    logger.info(
        "Total %d activities from %d file(s)",
        len(all_activities),
        len(files),
    )
    return all_activities


def _parse_fit_file_id(data: bytes) -> tuple[int, datetime | None] | None:
    if len(data) < 14:
        return None
    header_size = data[0]
    if header_size not in (12, 14):
        return None
    if data[8:12] != FIT_MAGIC:
        return None

    pos = header_size
    rec_hdr = data[pos]
    if rec_hdr & 0x80:
        return None
    is_definition = bool(rec_hdr & 0x40)
    local_type = rec_hdr & 0x0F
    pos += 1

    if not is_definition:
        return None

    pos += 1
    if pos + 4 > len(data):
        return None
    arch = data[pos]
    pos += 1
    global_msg = struct.unpack_from("<H" if arch == 0 else ">H", data, pos)[0]
    pos += 2
    if global_msg != 0:
        return None

    if pos >= len(data):
        return None
    num_fields = data[pos]
    pos += 1

    field_defs: list[tuple[int, int]] = []
    for _ in range(num_fields):
        if pos + 3 > len(data):
            return None
        fnum = data[pos]
        fsize = data[pos + 1]
        pos += 3
        field_defs.append((fnum, fsize))

    if pos >= len(data):
        return None
    rec_hdr2 = data[pos]
    pos += 1
    if rec_hdr2 & 0x80:
        return None
    if bool(rec_hdr2 & 0x40) or (rec_hdr2 & 0x0F) != local_type:
        return None

    file_type_raw: int | None = None
    time_created: datetime | None = None
    for fnum, fsize in field_defs:
        if pos + fsize > len(data):
            return None
        raw = data[pos : pos + fsize]
        pos += fsize
        if fnum == 0 and fsize >= 1:
            file_type_raw = struct.unpack_from("<B", raw)[0]
        elif fnum == 4 and fsize >= 4:
            ts = struct.unpack_from("<I", raw)[0]
            time_created = FIT_EPOCH + timedelta(seconds=ts)

    if file_type_raw is None:
        return None
    return (file_type_raw, time_created)


def _find_uploaded_dir(extracted_dir: Path) -> Path | None:
    for candidate in (
        extracted_dir / "DI_CONNECT" / "DI-Connect-Uploaded-Files",
        extracted_dir / "DI-Connect-Uploaded-Files",
    ):
        if candidate.exists():
            return candidate
    return None


def _extract_activity_files_from_zips(
    uploaded_dir: Path,
) -> list[Path]:
    tmp_dir = tempfile.mkdtemp(prefix="garmin_uploaded_")
    extracted: list[Path] = []
    zip_files = sorted(uploaded_dir.glob("*.zip"))
    total_scanned = 0

    for zip_path in zip_files:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".fit"):
                    continue
                with zf.open(name) as f:
                    data = f.read()
                total_scanned += 1
                result = _parse_fit_file_id(data)
                if result is None or result[0] != FIT_FILE_TYPE_ACTIVITY:
                    continue
                out_path = Path(tmp_dir) / name.replace("/", "_")
                out_path.write_bytes(data)
                extracted.append(out_path)

    logger.info(
        "Scanned %d FIT files from %d ZIP(s), found %d activity files",
        total_scanned,
        len(zip_files),
        len(extracted),
    )
    return extracted


def find_uploaded_activity_files(extracted_dir: Path) -> list[Path]:
    uploaded_dir = _find_uploaded_dir(extracted_dir)
    if uploaded_dir is None:
        logger.warning("Uploaded files directory not found")
        return []

    extensions = {".gpx", ".fit", ".tcx"}
    direct_files = [
        p
        for p in sorted(uploaded_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in extensions
    ]

    zip_extracted = _extract_activity_files_from_zips(uploaded_dir)

    all_files = direct_files + zip_extracted
    logger.info("Found %d uploaded activity file(s)", len(all_files))
    return all_files


def _extract_gpx_start_time(path: Path) -> datetime | None:
    try:
        import gpxpy

        with open(path) as f:
            gpx = gpxpy.parse(f)
        for track in gpx.tracks:
            for segment in track.segments:
                if segment.points and segment.points[0].time:
                    return segment.points[0].time
    except Exception as exc:
        logger.debug("Failed to parse GPX file %s: %s", path, exc)
    return None


def _extract_fit_start_time(path: Path) -> datetime | None:
    try:
        data = path.read_bytes()
        result = _parse_fit_file_id(data)
        if result is not None:
            return result[1]
    except Exception as exc:
        logger.debug("Failed to parse FIT file %s: %s", path, exc)
    return None


def _extract_tcx_start_time(path: Path) -> datetime | None:
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(path)
        root = tree.getroot()
        ns = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"

        for activity in root.iter(f"{{{ns}}}Activity"):
            id_el = activity.find(f"{{{ns}}}Id")
            if id_el is not None and id_el.text:
                return datetime.fromisoformat(id_el.text)

        for lap in root.iter(f"{{{ns}}}Lap"):
            start = lap.get("StartTime")
            if start:
                return datetime.fromisoformat(start)
    except Exception as exc:
        logger.debug("Failed to parse TCX file %s: %s", path, exc)
    return None


def build_uploaded_files_table(
    extracted_dir: Path,
) -> dict[datetime, Path]:
    files = find_uploaded_activity_files(extracted_dir)
    multi: dict[datetime, list[Path]] = {}

    for f in files:
        start_time: datetime | None = None
        suffix = f.suffix.lower()
        if suffix == ".gpx":
            start_time = _extract_gpx_start_time(f)
        elif suffix == ".fit":
            start_time = _extract_fit_start_time(f)
        elif suffix == ".tcx":
            start_time = _extract_tcx_start_time(f)

        if start_time is not None:
            multi.setdefault(start_time, []).append(f)

    table: dict[datetime, Path] = {}
    for ts, paths in multi.items():
        if len(paths) > 1:
            kept = max(paths, key=lambda p: p.stat().st_size)
            discarded = [p.name for p in paths if p != kept]
            logger.warning(
                "[MULTI-MATCH] activity_start=%s — multiple files share the same "
                "start time, keeping '%s' (discarded: %s)",
                ts.strftime("%Y-%m-%d %H:%M:%S"),
                kept.name,
                ", ".join(f"'{n}'" for n in discarded),
            )
            table[ts] = kept
        else:
            table[ts] = paths[0]

    logger.info("Built uploaded files table with %d entries", len(table))
    return table


def find_matching_file(
    activity_start: datetime,
    files_table: dict[datetime, Path],
    margin_seconds: int = 10,
    activity_name: str | None = None,
) -> Path | None:
    offsets = [
        timedelta(hours=h)
        for h in range(-12, 15)
    ]
    matches: list[tuple[datetime, Path]] = []
    for offset in offsets:
        adjusted = activity_start - offset
        for file_start, file_path in files_table.items():
            diff = abs((adjusted - file_start).total_seconds())
            if diff <= margin_seconds:
                matches.append((file_start, file_path))

    if not matches:
        return None

    if len(matches) > 1:
        kept = max(matches, key=lambda m: m[1].stat().st_size)
        candidates = [
            f"'{p.name}' at {ts.strftime('%Y-%m-%d %H:%M:%S')}"
            for ts, p in matches
            if (ts, p) != kept
        ]
        label = (
            f"activity '{activity_name}'"
            if activity_name
            else f"activity_start={activity_start.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        logger.warning(
            "[MULTI-MATCH] %s — multiple files within margin, keeping '%s' "
            "(candidates: %s)",
            label,
            kept[1].name,
            ", ".join(candidates),
        )
        return kept[1]

    return matches[0][1]


FIT_RECORD_MSG = 20
FIT_FIELD_POS_LAT = 0
FIT_FIELD_POS_LON = 1
FIT_INVALID_INT32 = 0x7FFFFFFF


def _check_fit_for_gps(data: bytes) -> bool:
    if len(data) < 14:
        return False

    header_size = data[0]
    if header_size not in (12, 14):
        return False
    if data[8:12] != FIT_MAGIC:
        return False

    data_size = struct.unpack_from("<I", data, 4)[0]
    end = min(header_size + data_size, len(data))
    supports_dev = data[1] >= 20

    definitions: dict[int, tuple[int, list[tuple[int, int, int]]]] = {}
    pos = header_size

    while pos < end:
        if pos >= len(data):
            break
        rec_hdr = data[pos]
        pos += 1

        if rec_hdr & 0x80:
            local_type = (rec_hdr >> 4) & 0x03
            if local_type not in definitions:
                break
            _, fields = definitions[local_type]
            total = sum(fs for _, fs, _ in fields)
            pos += total
            continue

        local_type = rec_hdr & 0x0F
        is_definition = bool(rec_hdr & 0x40)

        if is_definition:
            if pos + 5 > end:
                break
            pos += 1
            arch = data[pos]
            pos += 1
            global_msg = struct.unpack_from(
                "<H" if arch == 0 else ">H", data, pos
            )[0]
            pos += 2
            num_fields = data[pos]
            pos += 1

            if pos + num_fields * 3 > end:
                break

            new_fields: list[tuple[int, int, int]] = []
            offset = 0
            for _ in range(num_fields):
                fnum = data[pos]
                fsize = data[pos + 1]
                pos += 3
                new_fields.append((fnum, fsize, offset))
                offset += fsize

            if supports_dev and pos < end:
                next_byte = data[pos]
                if next_byte < 64 and pos + 1 + next_byte * 3 <= end:
                    pos += 1 + next_byte * 3

            definitions[local_type] = (global_msg, new_fields)
        else:
            if local_type not in definitions:
                break
            global_msg, fields = definitions[local_type]
            total = sum(fs for _, fs, _ in fields)
            if pos + total > end:
                break

            if global_msg == FIT_RECORD_MSG:
                lat: int | None = None
                lon: int | None = None
                for fnum, fsize, foffset in fields:
                    if (
                        fnum == FIT_FIELD_POS_LAT
                        and fsize >= 4
                        and pos + foffset + 4 <= len(data)
                    ):
                        lat = struct.unpack_from("<i", data, pos + foffset)[0]
                    elif (
                        fnum == FIT_FIELD_POS_LON
                        and fsize >= 4
                        and pos + foffset + 4 <= len(data)
                    ):
                        lon = struct.unpack_from("<i", data, pos + foffset)[0]

                if (
                    lat is not None
                    and lon is not None
                    and lat != 0
                    and lon != 0
                    and lat != FIT_INVALID_INT32
                ):
                    return True

            pos += total

    return False


def _gpx_has_gps_data(path: Path) -> bool:
    try:
        import gpxpy

        with open(path) as f:
            gpx = gpxpy.parse(f)
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if point.latitude != 0 or point.longitude != 0:
                        return True
    except Exception as exc:
        logger.debug("Failed to parse GPX file %s: %s", path, exc)
        return True
    return False


def _fit_has_gps_data(path: Path) -> bool:
    try:
        data = path.read_bytes()
        return _check_fit_for_gps(data)
    except Exception as exc:
        logger.debug("Failed to check FIT GPS data %s: %s", path, exc)
        return True


def _tcx_has_gps_data(path: Path) -> bool:
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(path)
        root = tree.getroot()
        ns = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
        for tp in root.iter(f"{{{ns}}}Trackpoint"):
            pos = tp.find(f"{{{ns}}}Position")
            if pos is not None:
                lat_el = pos.find(f"{{{ns}}}LatitudeDegrees")
                if lat_el is not None and lat_el.text:
                    return True
    except Exception as exc:
        logger.debug("Failed to parse TCX file %s: %s", path, exc)
        return True
    return False


def has_gps_data(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".gpx":
        return _gpx_has_gps_data(path)
    if suffix == ".fit":
        return _fit_has_gps_data(path)
    if suffix == ".tcx":
        return _tcx_has_gps_data(path)
    return True


def patch_gpx_creator(path: Path, creator: str, tmp_dir: str | Path) -> Path:
    import xml.etree.ElementTree as ET

    tree = ET.parse(path)
    root = tree.getroot()
    root.set("creator", creator)
    out_dir = Path(tmp_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / path.name
    tree.write(str(out_path), xml_declaration=True, encoding="utf-8")
    return out_path


def patch_tcx_creator(path: Path, creator: str, tmp_dir: str | Path) -> Path:
    import xml.etree.ElementTree as ET

    ns = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
    ET.register_namespace("", ns)
    tree = ET.parse(path)
    root = tree.getroot()
    for activity in root.iter(f"{{{ns}}}Activity"):
        creator_el = activity.find(f"{{{ns}}}Creator")
        if creator_el is not None:
            name_el = creator_el.find(f"{{{ns}}}Name")
            if name_el is not None:
                name_el.text = creator
            else:
                name_el = ET.SubElement(creator_el, f"{{{ns}}}Name")
                name_el.text = creator
    out_dir = Path(tmp_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / path.name
    tree.write(str(out_path), xml_declaration=True, encoding="utf-8")
    return out_path


FIT_CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]


def _fit_crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = FIT_CRC_TABLE[byte & 0x0F]
        crc = (crc >> 4) ^ tmp
        tmp = FIT_CRC_TABLE[(byte >> 4) & 0x0F]
        crc = (crc >> 4) ^ tmp
    return crc


def _find_product_field_offset(
    data: bytes, header_size: int
) -> tuple[int, int] | None:
    pos = header_size
    if pos >= len(data):
        return None

    rec_hdr = data[pos]
    if rec_hdr & 0x80 or not (rec_hdr & 0x40):
        return None

    pos += 1
    if pos + 4 > len(data):
        return None
    pos += 1
    arch = data[pos]
    pos += 1
    global_msg = struct.unpack_from("<H" if arch == 0 else ">H", data, pos)[0]
    pos += 2

    if global_msg != 0:
        return None

    if pos >= len(data):
        return None
    num_fields = data[pos]
    pos += 1

    field_offset = 0
    product_offset_in_data = -1
    product_size = 0
    for i in range(num_fields):
        if pos + 3 > len(data):
            return None
        fnum = data[pos]
        fsize = data[pos + 1]
        pos += 3
        if fnum == 2 and product_offset_in_data < 0:
            product_offset_in_data = field_offset
            product_size = fsize
        field_offset += fsize

    if product_offset_in_data < 0:
        return None

    if pos >= len(data):
        return None
    rec_hdr2 = data[pos]
    if rec_hdr2 & 0x80 or (rec_hdr2 & 0x40) or (rec_hdr2 & 0x0F) != 0:
        return None

    data_start = pos + 1
    if data_start + product_offset_in_data + product_size > len(data):
        return None
    return data_start + product_offset_in_data, product_size


def patch_fit_product(
    path: Path, product_id: int, tmp_dir: str | Path
) -> Path | None:
    data = path.read_bytes()
    if len(data) < 16:
        return None

    header_size = data[0]
    if header_size not in (12, 14):
        return None
    if data[8:12] != FIT_MAGIC:
        return None

    result = _find_product_field_offset(data, header_size)
    if result is None:
        return None

    offset, size = result
    if size < 2:
        return None

    patched = bytearray(data)
    struct.pack_into("<H", patched, offset, product_id & 0xFFFF)

    crc_data = bytes(patched[:-2])
    new_crc = _fit_crc16(crc_data)
    struct.pack_into("<H", patched, len(patched) - 2, new_crc)

    out_dir = Path(tmp_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / path.name
    out_path.write_bytes(bytes(patched))
    return out_path
