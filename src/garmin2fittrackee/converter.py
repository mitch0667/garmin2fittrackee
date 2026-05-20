import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from garmin2fittrackee import GearError
from garmin2fittrackee.fittrackee.client import FitTrackeeClient
from garmin2fittrackee.fittrackee.models import (
    FitTrackeeEquipment,
    FitTrackeeEquipmentCreate,
    FitTrackeeEquipmentType,
    FitTrackeeEquipmentUpdate,
    FitTrackeeSport,
    FitTrackeeWorkout,
    FitTrackeeWorkoutCreateNoGpx,
    FitTrackeeWorkoutUpdate,
)
from garmin2fittrackee.garmin.activities import (
    GarminActivity,
    find_matching_file,
    has_gps_data,
    patch_fit_product,
    patch_gpx_creator,
    patch_tcx_creator,
)
from garmin2fittrackee.garmin.garmin_products import resolve_product_id
from garmin2fittrackee.garmin.gear import GarminGear
from garmin2fittrackee.mapping import resolve_equipment_type_id, resolve_sport_id

logger = logging.getLogger(__name__)

DUPLICATE_MARGIN_SECONDS = 10


@dataclass(frozen=True)
class EquipmentSyncResult:
    created: int
    updated: int
    skipped: int
    unmapped: int


@dataclass(frozen=True)
class ActivitySyncResult:
    created: int
    updated: int
    skipped: int
    unmapped: int
    errors: int


def _format_activity_counters(
    created: int, updated: int, skipped: int, unmapped: int, errors: int, total: int
) -> str:
    processed = created + updated + skipped + unmapped + errors
    return (
        f"([green]+{created} created[/green]  "
        f"[blue]↻{updated} updated[/blue]  "
        f"[grey]⏭{skipped} skipped[/grey]  "
        f"[red]✗{errors} errors[/red])  "
        f"{processed} / {total}"
    )


def _format_equipment_counters(
    created: int, updated: int, skipped: int, unmapped: int, total: int
) -> str:
    processed = created + updated + skipped + unmapped
    return (
        f"([green]+{created} created[/green]  "
        f"[blue]↻{updated} updated[/blue]  "
        f"[grey]⏭{skipped} skipped[/grey]  "
        f"[yellow]?{unmapped} unmapped[/yellow])  "
        f"{processed} / {total}"
    )


def convert_gear(
    gear: GarminGear,
    mapping: dict[str, str],
    ft_types: list[FitTrackeeEquipmentType],
) -> FitTrackeeEquipmentCreate | None:
    type_id = resolve_equipment_type_id(
        gear.gear_type_name, mapping, ft_types
    )
    if type_id is None:
        return None

    return FitTrackeeEquipmentCreate(
        label=gear.label,
        equipment_type_id=type_id,
        description=f"Synced from Garmin (original type: {gear.gear_type_name})",
        is_active=gear.is_active,
    )


def check_duplicate_labels(gears: list[GarminGear]) -> None:
    seen: dict[str, list[int]] = {}
    for gear in gears:
        seen.setdefault(gear.label, []).append(gear.gear_pk)
    duplicates = {label: pks for label, pks in seen.items() if len(pks) > 1}
    if duplicates:
        details = "; ".join(
            f"'{label}' (PKs: {pks})" for label, pks in duplicates.items()
        )
        raise GearError(f"Duplicate gear labels found: {details}")


def _needs_update(
    existing: FitTrackeeEquipment, desired: FitTrackeeEquipmentCreate
) -> FitTrackeeEquipmentUpdate | None:
    label: str | None = None
    equipment_type_id: int | None = None
    is_active: bool | None = None
    description: str | None = None
    changed = False

    if existing.label != desired.label:
        label = desired.label
        changed = True
    if existing.is_active != desired.is_active:
        is_active = desired.is_active
        changed = True
    if existing.equipment_type.id != desired.equipment_type_id:
        equipment_type_id = desired.equipment_type_id
        changed = True
    if existing.description != desired.description:
        description = desired.description
        changed = True

    if not changed:
        return None

    return FitTrackeeEquipmentUpdate(
        label=label,
        equipment_type_id=equipment_type_id,
        is_active=is_active,
        description=description,
    )


def sync_equipments(
    gears: list[GarminGear],
    client: FitTrackeeClient,
    mapping: dict[str, str],
    ft_types: list[FitTrackeeEquipmentType],
    *,
    dry_run: bool = False,
    force_active: bool = False,
) -> EquipmentSyncResult:
    check_duplicate_labels(gears)

    existing_map: dict[str, FitTrackeeEquipment] = {}
    if not dry_run:
        for eq in client.get_equipments():
            existing_map[eq.label] = eq

    created = 0
    updated = 0
    skipped = 0
    unmapped = 0
    total = len(gears)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TextColumn("{task.fields[counters]}"),
    ) as progress:
        task = progress.add_task(
            "Syncing equipments...", total=total, counters=""
        )

        for gear in gears:
            desired = convert_gear(gear, mapping, ft_types)
            if desired is not None and force_active:
                desired = desired.model_copy(update={"is_active": True})
            if desired is None:
                unmapped += 1
                progress.update(
                    task,
                    counters=_format_equipment_counters(
                        created, updated, skipped, unmapped, total
                    ),
                )
                progress.advance(task)
                continue

            existing = existing_map.get(gear.label)
            if existing is None:
                logger.info(
                    "[CREATE] '%s' (type_id=%d, active=%s)",
                    desired.label,
                    desired.equipment_type_id,
                    desired.is_active,
                )
                if not dry_run:
                    client.create_equipment(desired)
                created += 1
                progress.update(
                    task,
                    counters=_format_equipment_counters(
                        created, updated, skipped, unmapped, total
                    ),
                )
                progress.advance(task)
                continue

            patch = _needs_update(existing, desired)
            if patch is None:
                logger.info("[SKIP] '%s' — no changes", gear.label)
                skipped += 1
                progress.update(
                    task,
                    counters=_format_equipment_counters(
                        created, updated, skipped, unmapped, total
                    ),
                )
                progress.advance(task)
                continue

            logger.info(
                "[UPDATE] '%s' — %s", gear.label, patch.model_dump(exclude_none=True)
            )
            if not dry_run:
                client.update_equipment(existing.id, patch)
            updated += 1
            progress.update(
                task,
                counters=_format_equipment_counters(
                    created, updated, skipped, unmapped, total
                ),
            )
            progress.advance(task)

    logger.info(
        "Sync complete: %d created, %d updated, %d skipped, %d unmapped",
        created,
        updated,
        skipped,
        unmapped,
    )
    return EquipmentSyncResult(
        created=created, updated=updated, skipped=skipped, unmapped=unmapped
    )


def resolve_equipment_ids(
    activity_id: int,
    gear_mapping: dict[int, list[int]],
    gear_by_pk: dict[int, GarminGear],
    ft_equipments: dict[str, FitTrackeeEquipment],
) -> list[str]:
    gear_pks = gear_mapping.get(activity_id, [])
    if not gear_pks:
        return []
    ids: list[str] = []
    for pk in gear_pks:
        gear = gear_by_pk.get(pk)
        if gear is None:
            logger.debug("Gear pk=%d not found in gear definitions", pk)
            continue
        eq = ft_equipments.get(gear.label)
        if eq is not None:
            ids.append(eq.id)
        else:
            logger.warning(
                "Equipment '%s' (gear pk=%d) not found in FitTrackee",
                gear.label,
                pk,
            )
    return ids


def _needs_workout_update(
    existing: FitTrackeeWorkout,
    desired: FitTrackeeWorkoutCreateNoGpx,
) -> FitTrackeeWorkoutUpdate | None:
    title: str | None = None
    description: str | None = None
    equipment_ids: list[str] | None = None
    changed = False

    if desired.title is not None and existing.title != desired.title:
        title = desired.title
        changed = True
    if desired.description is not None and existing.description != desired.description:
        description = desired.description
        changed = True

    desired_eq = set(desired.equipment_ids) if desired.equipment_ids else set()
    existing_eq = set(existing.equipment_ids) if existing.equipment_ids else set()
    if desired_eq != existing_eq:
        equipment_ids = sorted(desired_eq) if desired_eq else []
        changed = True

    if not changed:
        return None

    return FitTrackeeWorkoutUpdate(
        title=title,
        description=description,
        equipment_ids=equipment_ids,
    )


def _build_description(activity: GarminActivity) -> str:
    parts = [f"Synced from Garmin (type: {activity.activity_type_key})"]
    if activity.device_product_name:
        parts.append(f"Device: {activity.device_product_name}")
    return " | ".join(parts)


def convert_activity(
    activity: GarminActivity,
    sport_id: int,
    equipment_ids: list[str] | None = None,
) -> FitTrackeeWorkoutCreateNoGpx:
    return FitTrackeeWorkoutCreateNoGpx(
        sport_id=sport_id,
        duration=activity.duration_seconds,
        distance=activity.distance_km,
        workout_date=activity.start_time_local,
        title=activity.title,
        description=_build_description(activity),
        ascent=activity.elevation_gain_m if activity.elevation_gain_m > 0 else None,
        descent=activity.elevation_loss_m if activity.elevation_loss_m > 0 else None,
        equipment_ids=equipment_ids,
    )


def _parse_workout_date(date_str: str) -> datetime:
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse workout date: {date_str}")


def find_duplicate(
    activity_start: datetime,
    existing_workouts: list[FitTrackeeWorkout],
) -> FitTrackeeWorkout | None:
    for workout in existing_workouts:
        try:
            workout_dt = _parse_workout_date(workout.workout_date)
        except ValueError:
            logger.warning(
                "Failed to parse workout_date '%s' for workout id=%s",
                workout.workout_date,
                workout.id,
            )
            continue
        diff = abs((activity_start - workout_dt).total_seconds())
        if diff <= DUPLICATE_MARGIN_SECONDS:
            logger.debug(
                "Duplicate found: activity_start=%s, workout_dt=%s, diff=%.1fs",
                activity_start,
                workout_dt,
                diff,
            )
            return workout
    return None


def sync_activities(
    activities: list[GarminActivity],
    client: FitTrackeeClient,
    mapping: dict[str, str],
    sports: list[FitTrackeeSport],
    uploaded_files: dict[datetime, Path],
    *,
    dry_run: bool = False,
    with_gpx_only: bool = False,
    ft_equipments: dict[str, FitTrackeeEquipment] | None = None,
    gear_mapping: dict[int, list[int]] | None = None,
    gear_by_pk: dict[int, GarminGear] | None = None,
) -> ActivitySyncResult:
    existing_workouts: list[FitTrackeeWorkout] = []
    if not dry_run:
        existing_workouts = client.get_all_workouts()
        logger.info(
            "Fetched %d existing workouts from FitTrackee",
            len(existing_workouts),
        )

    equip_map = ft_equipments if ft_equipments is not None else {}
    g_map = gear_mapping if gear_mapping is not None else {}
    g_by_pk = gear_by_pk if gear_by_pk is not None else {}

    created = 0
    updated = 0
    skipped = 0
    unmapped = 0
    errors = 0

    _staging_dir: str | None = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TextColumn("{task.fields[counters]}"),
    ) as progress:
        task = progress.add_task(
            "Syncing activities...", total=len(activities), counters=""
        )
        total = len(activities)

        def _advance() -> None:
            progress.update(
                task,
                counters=_format_activity_counters(
                    created, updated, skipped, unmapped, errors, total
                ),
            )
            progress.advance(task)

        for activity in activities:
            sport_id = resolve_sport_id(
                activity.activity_type_key, mapping, sports
            )
            if sport_id is None:
                unmapped += 1
                _advance()
                continue

            activity_start = activity.start_datetime

            duplicate = (
                find_duplicate(activity_start, existing_workouts)
                if not dry_run
                else None
            )

            if not dry_run and duplicate is not None:
                equipment_ids = resolve_equipment_ids(
                    activity.activity_id, g_map, g_by_pk, equip_map
                )
                desired = convert_activity(
                    activity,
                    sport_id,
                    equipment_ids=equipment_ids or None,
                )
                logger.info(
                    "Activity id=%d: pushing workout_date='%s' "
                    "to FitTrackee for update (from json start_time_local)",
                    activity.activity_id,
                    desired.workout_date,
                )
                patch = _needs_workout_update(duplicate, desired)
                if patch is not None:
                    logger.info(
                        "[UPDATE] '%s' — %s",
                        activity.title or activity.activity_type_key,
                        patch.model_dump(exclude_none=True),
                    )
                    try:
                        if not dry_run:
                            client.update_workout(duplicate.id, patch)
                        updated += 1
                    except Exception as exc:
                        logger.error(
                            "Failed to update workout '%s': %s",
                            activity.title or activity.activity_type_key,
                            exc,
                        )
                        errors += 1
                else:
                    logger.info(
                        "[SKIP] '%s' — duplicate, no changes",
                        activity.title or activity.activity_type_key,
                    )
                    skipped += 1
                _advance()
                continue

            matching_file = find_matching_file(
                activity_start, uploaded_files
            )
            logger.info(
                "Activity id=%d '%s' (type=%s, json_start_local=%s, "
                "json_start_gmt=%s) -> file: %s",
                activity.activity_id,
                activity.title or activity.activity_type_key,
                activity.activity_type_key,
                activity.start_time_local,
                activity.start_time_gmt,
                matching_file.name if matching_file else "none",
            )

            if with_gpx_only and matching_file is None:
                logger.debug(
                    "[SKIP] '%s' — no matching file",
                    activity.title or activity.activity_type_key,
                )
                skipped += 1
                _advance()
                continue

            if with_gpx_only and matching_file is not None:
                if not has_gps_data(matching_file):
                    logger.warning(
                        "[SKIP] '%s' — file has no GPS data (%s)",
                        activity.title or activity.activity_type_key,
                        matching_file.name,
                    )
                    skipped += 1
                    _advance()
                    continue

            equipment_ids = resolve_equipment_ids(
                activity.activity_id, g_map, g_by_pk, equip_map
            )
            workout_data = convert_activity(
                activity, sport_id,
                equipment_ids=equipment_ids or None,
            )
            logger.info(
                "Activity id=%d: pushing workout_date='%s' "
                "to FitTrackee (from json start_time_local)",
                activity.activity_id,
                workout_data.workout_date,
            )

            try:
                if matching_file is not None and not dry_run:
                    upload_file = matching_file
                    if activity.device_product_name:
                        ext = matching_file.suffix.lower()
                        if ext == ".gpx":
                            if _staging_dir is None:
                                _staging_dir = tempfile.mkdtemp(
                                    prefix="gpx_patched_"
                                )
                            upload_file = patch_gpx_creator(
                                matching_file,
                                activity.device_product_name,
                                _staging_dir,
                            )
                        elif ext == ".tcx":
                            if _staging_dir is None:
                                _staging_dir = tempfile.mkdtemp(
                                    prefix="gpx_patched_"
                                )
                            upload_file = patch_tcx_creator(
                                matching_file,
                                activity.device_product_name,
                                _staging_dir,
                            )
                        elif ext == ".fit":
                            product_id = resolve_product_id(
                                activity.device_product_name
                            )
                            if product_id is not None:
                                if _staging_dir is None:
                                    _staging_dir = tempfile.mkdtemp(
                                        prefix="gpx_patched_"
                                    )
                                patched = patch_fit_product(
                                    matching_file,
                                    product_id,
                                    _staging_dir,
                                )
                                if patched is not None:
                                    upload_file = patched
                                    logger.info(
                                        "Patched FIT product ID to %d (%s)",
                                        product_id,
                                        activity.device_product_name,
                                    )
                    logger.info(
                        "[CREATE] '%s' with file %s (equipment: %s)",
                        activity.title or activity.activity_type_key,
                        upload_file,
                        equipment_ids or [],
                    )
                    client.create_workout_with_file(
                        workout_data, str(upload_file)
                    )
                elif not dry_run:
                    logger.info(
                        "[CREATE] '%s' (no file, equipment: %s)",
                        activity.title or activity.activity_type_key,
                        equipment_ids or [],
                    )
                    client.create_workout_no_gpx(workout_data)
                else:
                    logger.info(
                        "[DRY-RUN] Would create '%s' (equipment: %s)",
                        activity.title or activity.activity_type_key,
                        equipment_ids or [],
                    )
                created += 1
            except Exception as exc:
                logger.error(
                    "Failed to create workout for '%s': %s",
                    activity.title or activity.activity_type_key,
                    exc,
                )
                errors += 1

            _advance()

    logger.info(
        "Activity sync complete: %d created, %d updated, %d skipped (duplicates), "
        "%d unmapped, %d errors",
        created,
        updated,
        skipped,
        unmapped,
        errors,
    )
    return ActivitySyncResult(
        created=created, updated=updated, skipped=skipped,
        unmapped=unmapped, errors=errors
    )
