import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from garmin2fittrackee import GearError

logger = logging.getLogger(__name__)


class GarminGear(BaseModel):
    gear_pk: int = Field(alias="gearPk")
    gear_type_name: str = Field(alias="gearTypeName")
    gear_status_name: str = Field(alias="gearStatusName")
    custom_make_model: str = Field(alias="customMakeModel")
    display_name: str | None = Field(default=None, alias="displayName")
    date_begin: str = Field(alias="dateBegin")
    date_end: str | None = Field(default=None, alias="dateEnd")
    maximum_meters: float = Field(alias="maximumMeters")

    model_config = {"populate_by_name": True}

    @property
    def label(self) -> str:
        raw = self.display_name or self.custom_make_model
        if len(raw) > 50:
            return raw[:47] + "..."
        return raw

    @property
    def is_active(self) -> bool:
        return self.gear_status_name == "active"


def parse_gear_file(path: Path) -> list[GarminGear]:
    if not path.exists():
        raise GearError(f"Gear file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GearError(f"Invalid gear JSON in {path}: {exc}") from exc

    if isinstance(data, list):
        items: list[object] = []
        for entry in data:
            if isinstance(entry, dict) and "gearDTOS" in entry:
                items.extend(entry["gearDTOS"])
            else:
                items.append(entry)
    elif isinstance(data, dict) and "gearDTOS" in data:
        items = data["gearDTOS"]
    else:
        raise GearError(f"Unexpected gear data structure in {path}")

    gears: list[GarminGear] = []
    for item in items:
        try:
            gears.append(GarminGear.model_validate(item))
        except Exception as exc:
            logger.warning("Skipping invalid gear entry: %s", exc)

    logger.info("Parsed %d gear items from %s", len(gears), path)
    return gears


def find_gear_files(extracted_dir: Path) -> list[Path]:
    files = sorted(extracted_dir.rglob("*_gear.json"))
    logger.info("Found %d gear file(s) in %s", len(files), extracted_dir)
    return files


def parse_gear_activity_mapping(path: Path) -> dict[int, list[int]]:
    if not path.exists():
        raise GearError(f"Gear file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GearError(f"Invalid gear JSON in {path}: {exc}") from exc

    raw: list[object] = []
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = [data]

    reverse: dict[int, list[int]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        gad = entry.get("gearActivityDTOs")
        if not isinstance(gad, dict):
            continue
        for gear_pk_str, activity_list in gad.items():
            if not isinstance(activity_list, list):
                continue
            for item in activity_list:
                if isinstance(item, dict) and "activityId" in item:
                    aid = item["activityId"]
                    if isinstance(aid, (int, float)):
                        reverse.setdefault(int(aid), []).append(int(gear_pk_str))

    logger.info(
        "Parsed gear-activity mapping: %d activities with gear from %s",
        len(reverse),
        path,
    )
    return reverse


def parse_all_gear_activity_mappings(
    extracted_dir: Path,
) -> dict[int, list[int]]:
    files = find_gear_files(extracted_dir)
    combined: dict[int, list[int]] = {}
    for f in files:
        mapping = parse_gear_activity_mapping(f)
        for aid, pks in mapping.items():
            combined.setdefault(aid, []).extend(pks)
    return combined
