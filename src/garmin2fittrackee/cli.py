import logging
import zipfile
from pathlib import Path
from typing import Annotated, Optional

import typer

from garmin2fittrackee import ArchiveError
from garmin2fittrackee.config import (
    DEFAULT_EXTRACT_FOLDER,
    FitTrackeeConfig,
    default_log_file,
)
from garmin2fittrackee.converter import sync_activities, sync_equipments
from garmin2fittrackee.fittrackee.client import FitTrackeeClient
from garmin2fittrackee.fittrackee.models import FitTrackeeEquipment
from garmin2fittrackee.garmin.activities import (
    build_uploaded_files_table,
    parse_all_activities,
)
from garmin2fittrackee.garmin.archive import extract_archive
from garmin2fittrackee.garmin.gear import (
    GarminGear,
    find_gear_files,
    parse_all_gear_activity_mappings,
    parse_gear_file,
)
from garmin2fittrackee.logging_setup import setup_logging
from garmin2fittrackee.mapping import load_activity_mapping, load_mapping

app = typer.Typer(
    help="CLI tool to process Garmin data exports and push to FitTrackee.",
)

logger = logging.getLogger(__name__)


@app.callback()
def _main() -> None:
    pass


@app.command()
def extract(
    archive: Annotated[
        Path,
        typer.Argument(
            help="Path to Garmin export ZIP archive",
            exists=True,
        ),
    ],
    extract_folder: Annotated[
        Optional[Path],
        typer.Option(
            "--extract-folder",
            help="Folder to extract archive into",
        ),
    ] = None,
    log_file: Annotated[
        Optional[Path],
        typer.Option(
            "--log-file",
            help="Path to log file (env: LOG_FILE)",
        ),
    ] = None,
    log_level: Annotated[
        Optional[str],
        typer.Option(
            "--log-level",
            help="File log level (env: LOG_LEVEL)",
        ),
    ] = None,
    console_log_level: Annotated[
        Optional[str],
        typer.Option(
            "--console-log-level",
            help="Console log level (env: CONSOLE_LOG_LEVEL)",
        ),
    ] = None,
) -> None:
    setup_logging(
        log_file or default_log_file(),
        file_log_level=log_level,
        console_log_level=console_log_level,
    )
    folder = extract_folder or DEFAULT_EXTRACT_FOLDER
    logger.info("Extract folder: %s", folder)

    try:
        target = extract_archive(archive, folder)
        typer.echo(f"Archive extracted to: {target}")
    except Exception as e:
        logger.error("Extraction failed: %s", e)
        raise typer.Exit(code=1) from e


def _resolve_config(
    fittrackee_url: str | None,
    username: str | None,
    password: str | None,
) -> tuple[str, str, str]:
    env_config = FitTrackeeConfig.from_env()
    url = fittrackee_url or env_config.url
    user = username or env_config.username
    pw = password or env_config.password

    missing = []
    if not url:
        missing.append("FITTRACKEE_URL")
    if not user:
        missing.append("FITTRACKEE_USERNAME")
    if not pw:
        missing.append("FITTRACKEE_PASSWORD")
    if missing:
        logger.error(
            "Missing required configuration: %s", ", ".join(missing)
        )
        raise typer.Exit(code=1)

    assert url is not None
    assert user is not None
    assert pw is not None

    return url, user, pw


def _resolve_archive_path(archive_path: Path) -> Path:
    if not archive_path.exists():
        raise ArchiveError(f"Path not found: {archive_path}")

    if archive_path.is_dir():
        return archive_path

    if archive_path.is_file():
        if not zipfile.is_zipfile(archive_path):
            raise ArchiveError(
                f"Not a valid ZIP archive: {archive_path}. "
                "Provide either an extracted directory or a .zip file."
            )
        logger.info(
            "ZIP archive detected, auto-extracting: %s", archive_path
        )
        target = extract_archive(archive_path, DEFAULT_EXTRACT_FOLDER)
        typer.echo(f"Auto-extracted archive to: {target}")
        return target

    raise ArchiveError(f"Invalid path: {archive_path}")


@app.command(name="sync-equipments")
def sync_equipments_cmd(
    archive_path: Annotated[
        Path,
        typer.Argument(
            help="Path to Garmin export directory or ZIP archive",
        ),
    ],
    fittrackee_url: Annotated[
        Optional[str],
        typer.Option(
            "--fittrackee-url",
            help="FitTrackee instance URL (env: FITTRACKEE_URL)",
        ),
    ] = None,
    username: Annotated[
        Optional[str],
        typer.Option(
            "--username",
            help="FitTrackee username (env: FITTRACKEE_USERNAME)",
        ),
    ] = None,
    password: Annotated[
        Optional[str],
        typer.Option(
            "--password",
            help="FitTrackee password (env: FITTRACKEE_PASSWORD)",
        ),
    ] = None,
    mapping_file: Annotated[
        Optional[Path],
        typer.Option(
            "--mapping-file",
            help="Path to custom TOML mapping file",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be synced without making changes",
        ),
    ] = False,
    force_active: Annotated[
        bool,
        typer.Option(
            "--force-active",
            help="Force all equipments as active regardless of Garmin status",
        ),
    ] = False,
    log_file: Annotated[
        Optional[Path],
        typer.Option(
            "--log-file",
            help="Path to log file (env: LOG_FILE)",
        ),
    ] = None,
    log_level: Annotated[
        Optional[str],
        typer.Option(
            "--log-level",
            help="File log level (env: LOG_LEVEL)",
        ),
    ] = None,
    console_log_level: Annotated[
        Optional[str],
        typer.Option(
            "--console-log-level",
            help="Console log level (env: CONSOLE_LOG_LEVEL)",
        ),
    ] = None,
) -> None:
    setup_logging(
        log_file or default_log_file(),
        file_log_level=log_level,
        console_log_level=console_log_level,
    )

    try:
        resolved_path = _resolve_archive_path(archive_path)
    except ArchiveError as e:
        logger.error("Invalid archive path: %s", e)
        raise typer.Exit(code=1) from e

    url, user, pw = _resolve_config(
        fittrackee_url, username, password
    )

    gear_files = find_gear_files(resolved_path)
    if not gear_files:
        typer.echo("No gear files found in archive.")
        return

    all_gears = []
    for gf in gear_files:
        all_gears.extend(parse_gear_file(gf))

    if not all_gears:
        typer.echo("No gear items found.")
        return

    mapping = load_mapping(mapping_file)
    logger.info("Using mapping: %s", mapping)

    client = FitTrackeeClient(
        base_url=url,
        username=user,
        password=pw,
    )

    try:
        ft_types = [] if dry_run else client.get_equipment_types()
        result = sync_equipments(
            all_gears, client, mapping, ft_types,
            dry_run=dry_run, force_active=force_active,
        )
        typer.echo(
            f"Equipment sync complete: {result.created} created, "
            f"{result.updated} updated, {result.skipped} skipped, "
            f"{result.unmapped} unmapped"
        )
    except Exception as e:
        logger.error("Sync failed: %s", e)
        raise typer.Exit(code=1) from e
    finally:
        client.close()


@app.command(name="sync-activities")
def sync_activities_cmd(
    archive_path: Annotated[
        Path,
        typer.Argument(
            help="Path to Garmin export directory or ZIP archive",
        ),
    ],
    fittrackee_url: Annotated[
        Optional[str],
        typer.Option(
            "--fittrackee-url",
            help="FitTrackee instance URL (env: FITTRACKEE_URL)",
        ),
    ] = None,
    username: Annotated[
        Optional[str],
        typer.Option(
            "--username",
            help="FitTrackee username (env: FITTRACKEE_USERNAME)",
        ),
    ] = None,
    password: Annotated[
        Optional[str],
        typer.Option(
            "--password",
            help="FitTrackee password (env: FITTRACKEE_PASSWORD)",
        ),
    ] = None,
    activity_mapping_file: Annotated[
        Optional[Path],
        typer.Option(
            "--activity-mapping-file",
            help="Path to custom activity type TOML mapping file",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be synced without making changes",
        ),
    ] = False,
    with_gpx_only: Annotated[
        bool,
        typer.Option(
            "--with-gpx-only",
            help="Only sync activities that have a matching GPX/FIT/TCX file",
        ),
    ] = False,
    log_file: Annotated[
        Optional[Path],
        typer.Option(
            "--log-file",
            help="Path to log file (env: LOG_FILE)",
        ),
    ] = None,
    log_level: Annotated[
        Optional[str],
        typer.Option(
            "--log-level",
            help="File log level (env: LOG_LEVEL)",
        ),
    ] = None,
    console_log_level: Annotated[
        Optional[str],
        typer.Option(
            "--console-log-level",
            help="Console log level (env: CONSOLE_LOG_LEVEL)",
        ),
    ] = None,
) -> None:
    setup_logging(
        log_file or default_log_file(),
        file_log_level=log_level,
        console_log_level=console_log_level,
    )

    try:
        resolved_path = _resolve_archive_path(archive_path)
    except ArchiveError as e:
        logger.error("Invalid archive path: %s", e)
        raise typer.Exit(code=1) from e

    url, user, pw = _resolve_config(
        fittrackee_url, username, password
    )

    try:
        activities = parse_all_activities(resolved_path)
    except Exception as e:
        logger.error("Failed to parse activities: %s", e)
        raise typer.Exit(code=1) from e

    if not activities:
        typer.echo("No activities found in archive.")
        return

    typer.echo(f"Found {len(activities)} activities.")

    mapping = load_activity_mapping(activity_mapping_file)
    logger.info("Using activity mapping: %s", mapping)

    uploaded_files = build_uploaded_files_table(resolved_path)

    gear_mapping = parse_all_gear_activity_mappings(resolved_path)
    gear_by_pk: dict[int, GarminGear] = {}
    for gf in find_gear_files(resolved_path):
        for g in parse_gear_file(gf):
            gear_by_pk[g.gear_pk] = g

    client = FitTrackeeClient(
        base_url=url,
        username=user,
        password=pw,
    )

    try:
        sports = [] if dry_run else client.get_sports()
        ft_equipments: dict[str, FitTrackeeEquipment] = {}
        if not dry_run:
            ft_equipments = {
                eq.label: eq for eq in client.get_equipments()
            }
        result = sync_activities(
            activities,
            client,
            mapping,
            sports,
            uploaded_files,
            dry_run=dry_run,
            with_gpx_only=with_gpx_only,
            ft_equipments=ft_equipments,
            gear_mapping=gear_mapping,
            gear_by_pk=gear_by_pk,
        )
        typer.echo(
            f"Activity sync complete: {result.created} created, "
            f"{result.updated} updated, "
            f"{result.skipped} skipped, {result.unmapped} unmapped, "
            f"{result.errors} errors"
        )
    except Exception as e:
        logger.error("Activity sync failed: %s", e)
        raise typer.Exit(code=1) from e
    finally:
        client.close()


@app.command(name="full-sync")
def full_sync_cmd(
    archive_path: Annotated[
        Path,
        typer.Argument(
            help="Path to Garmin export directory or ZIP archive",
        ),
    ],
    fittrackee_url: Annotated[
        Optional[str],
        typer.Option(
            "--fittrackee-url",
            help="FitTrackee instance URL (env: FITTRACKEE_URL)",
        ),
    ] = None,
    username: Annotated[
        Optional[str],
        typer.Option(
            "--username",
            help="FitTrackee username (env: FITTRACKEE_USERNAME)",
        ),
    ] = None,
    password: Annotated[
        Optional[str],
        typer.Option(
            "--password",
            help="FitTrackee password (env: FITTRACKEE_PASSWORD)",
        ),
    ] = None,
    mapping_file: Annotated[
        Optional[Path],
        typer.Option(
            "--mapping-file",
            help="Path to custom equipment TOML mapping file",
        ),
    ] = None,
    activity_mapping_file: Annotated[
        Optional[Path],
        typer.Option(
            "--activity-mapping-file",
            help="Path to custom activity type TOML mapping file",
        ),
    ] = None,
    with_gpx_only: Annotated[
        bool,
        typer.Option(
            "--with-gpx-only",
            help="Only sync activities that have a matching GPX/FIT/TCX file",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be synced without making changes",
        ),
    ] = False,
    log_file: Annotated[
        Optional[Path],
        typer.Option(
            "--log-file",
            help="Path to log file (env: LOG_FILE)",
        ),
    ] = None,
    log_level: Annotated[
        Optional[str],
        typer.Option(
            "--log-level",
            help="File log level (env: LOG_LEVEL)",
        ),
    ] = None,
    console_log_level: Annotated[
        Optional[str],
        typer.Option(
            "--console-log-level",
            help="Console log level (env: CONSOLE_LOG_LEVEL)",
        ),
    ] = None,
) -> None:
    setup_logging(
        log_file or default_log_file(),
        file_log_level=log_level,
        console_log_level=console_log_level,
    )

    try:
        resolved_path = _resolve_archive_path(archive_path)
    except ArchiveError as e:
        logger.error("Invalid archive path: %s", e)
        raise typer.Exit(code=1) from e

    url, user, pw = _resolve_config(
        fittrackee_url, username, password
    )

    gear_files = find_gear_files(resolved_path)
    all_gears: list[GarminGear] = []
    for gf in gear_files:
        all_gears.extend(parse_gear_file(gf))

    gear_mapping = parse_all_gear_activity_mappings(resolved_path)
    gear_by_pk: dict[int, GarminGear] = {}
    for gf in gear_files:
        for g in parse_gear_file(gf):
            gear_by_pk[g.gear_pk] = g

    try:
        activities = parse_all_activities(resolved_path)
    except Exception:
        activities = []

    eq_mapping = load_mapping(mapping_file)
    act_mapping = load_activity_mapping(activity_mapping_file)

    client = FitTrackeeClient(
        base_url=url,
        username=user,
        password=pw,
    )

    try:
        ft_types = [] if dry_run else client.get_equipment_types()

        if all_gears:
            typer.echo("=== Step 1/3: Sync equipments (force active) ===")
            result_eq = sync_equipments(
                all_gears, client, eq_mapping, ft_types,
                dry_run=dry_run, force_active=True,
            )
            typer.echo(
                f"Equipment sync: {result_eq.created} created, "
                f"{result_eq.updated} updated, {result_eq.skipped} skipped, "
                f"{result_eq.unmapped} unmapped"
            )
        else:
            typer.echo("=== Step 1/3: No gear found, skipping ===")

        if activities:
            typer.echo(
                f"=== Step 2/3: Sync activities ({len(activities)} found) ==="
            )
            sports = [] if dry_run else client.get_sports()
            uploaded_files = build_uploaded_files_table(resolved_path)
            ft_equipments: dict[str, FitTrackeeEquipment] = {}
            if not dry_run:
                ft_equipments = {
                    eq.label: eq for eq in client.get_equipments()
                }
            result_act = sync_activities(
                activities, client, act_mapping, sports, uploaded_files,
                dry_run=dry_run,
                with_gpx_only=with_gpx_only,
                ft_equipments=ft_equipments,
                gear_mapping=gear_mapping,
                gear_by_pk=gear_by_pk,
            )
            typer.echo(
                f"Activity sync: {result_act.created} created, "
                f"{result_act.updated} updated, "
                f"{result_act.skipped} skipped, {result_act.unmapped} unmapped, "
                f"{result_act.errors} errors"
            )
        else:
            typer.echo("=== Step 2/3: No activities found, skipping ===")

        if all_gears:
            typer.echo("=== Step 3/3: Sync equipments (actual state) ===")
            ft_types = [] if dry_run else client.get_equipment_types()
            result_eq2 = sync_equipments(
                all_gears, client, eq_mapping, ft_types,
                dry_run=dry_run, force_active=False,
            )
            typer.echo(
                f"Equipment re-sync: {result_eq2.created} created, "
                f"{result_eq2.updated} updated, {result_eq2.skipped} skipped, "
                f"{result_eq2.unmapped} unmapped"
            )
        else:
            typer.echo("=== Step 3/3: No gear found, skipping ===")

        typer.echo("Full sync complete.")
    except Exception as e:
        logger.error("Full sync failed: %s", e)
        raise typer.Exit(code=1) from e
    finally:
        client.close()


if __name__ == "__main__":
    app()
