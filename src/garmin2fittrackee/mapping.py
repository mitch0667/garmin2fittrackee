import logging
import tomllib
from pathlib import Path

from garmin2fittrackee import MappingError
from garmin2fittrackee.fittrackee.models import (
    FitTrackeeEquipmentType,
    FitTrackeeSport,
)

logger = logging.getLogger(__name__)

DEFAULT_EQUIPMENT_MAPPING_FILE = Path(__file__).parent / "equipment_mapping.toml"
DEFAULT_ACTIVITY_MAPPING_FILE = Path(__file__).parent / "activity_mapping.toml"


def load_mapping(config_path: Path | None = None) -> dict[str, str]:
    path = config_path or DEFAULT_EQUIPMENT_MAPPING_FILE
    if not path.exists():
        raise MappingError(f"Mapping file not found: {path}")

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        raise MappingError(f"Failed to parse mapping file {path}: {exc}") from exc

    mapping = data.get("gear_type_mapping", {})
    if not mapping:
        raise MappingError(f"No [gear_type_mapping] section in {path}")

    logger.info("Loaded %d gear type mapping(s) from %s", len(mapping), path)
    return dict(mapping)


def _find_type_id_by_label(
    label: str, ft_types: list[FitTrackeeEquipmentType]
) -> int | None:
    for ft_type in ft_types:
        if ft_type.label.lower() == label.lower() and ft_type.is_active:
            return ft_type.id
    return None


def resolve_equipment_type_id(
    gear_type_name: str,
    mapping: dict[str, str],
    ft_types: list[FitTrackeeEquipmentType],
    fallback_label: str = "Misc",
) -> int | None:
    mapped_label = mapping.get(gear_type_name)
    if mapped_label is None:
        fallback_id = _find_type_id_by_label(fallback_label, ft_types)
        if fallback_id is not None:
            logger.info(
                "No mapping for Garmin gear type '%s', "
                "using fallback type '%s' (id=%d)",
                gear_type_name,
                fallback_label,
                fallback_id,
            )
            return fallback_id
        logger.warning(
            "No mapping for Garmin gear type '%s' and "
            "fallback type '%s' not found or inactive, skipping",
            gear_type_name,
            fallback_label,
        )
        return None

    type_id = _find_type_id_by_label(mapped_label, ft_types)
    if type_id is not None:
        return type_id

    logger.debug(
        "FitTrackee equipment type '%s' not found or inactive "
        "for Garmin gear type '%s'",
        mapped_label,
        gear_type_name,
    )
    return None


def load_activity_mapping(config_path: Path | None = None) -> dict[str, str]:
    path = config_path or DEFAULT_ACTIVITY_MAPPING_FILE
    if not path.exists():
        raise MappingError(f"Activity mapping file not found: {path}")

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        raise MappingError(
            f"Failed to parse activity mapping file {path}: {exc}"
        ) from exc

    mapping = data.get("activity_type_mapping", {})
    if not mapping:
        raise MappingError(f"No [activity_type_mapping] section in {path}")

    logger.info(
        "Loaded %d activity type mapping(s) from %s", len(mapping), path
    )
    return dict(mapping)


def resolve_sport_id(
    activity_type_key: str,
    mapping: dict[str, str],
    sports: list[FitTrackeeSport],
) -> int | None:
    mapped_label = mapping.get(activity_type_key)
    if mapped_label is None:
        logger.warning(
            "No mapping for Garmin activity type '%s', skipping",
            activity_type_key,
        )
        return None

    if mapped_label == "Other":
        logger.info(
            "Activity type '%s' mapped to 'Other', skipping", activity_type_key
        )
        return None

    for sport in sports:
        if sport.label.lower() == mapped_label.lower() and sport.is_active:
            return sport.id

    logger.warning(
        "FitTrackee sport '%s' not found or inactive, "
        "skipping Garmin activity type '%s'",
        mapped_label,
        activity_type_key,
    )
    return None
