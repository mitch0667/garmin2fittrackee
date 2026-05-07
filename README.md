# garmin2fittrackee

CLI tool that processes Garmin data export archives (ZIP) and pushes sport activities to a self-hosted FitTrackee instance via its API.

## Dependencies
### uv
https://docs.astral.sh/uv/getting-started/installation/

To install last version:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Usage
Currently the tool has to be executed in two different steps:
1. First, sync equipments
2. Second, push activities

### Sync equipments to FitTrackee

```bash
uv run garmin2fittrackee sync-equipments <path_to_extracted_archive_or_zip> [OPTIONS]
```

Options:
- `--fittrackee-url <url>` — FitTrackee instance URL (env: `FITTRACKEE_URL`)
- `--username <user>` — FitTrackee username (env: `FITTRACKEE_USERNAME`)
- `--password <pass>` — FitTrackee password (env: `FITTRACKEE_PASSWORD`)
- `--mapping-file <path>` — Custom TOML mapping file (default: built-in)
- `--dry-run` — Show what would be synced without making changes

The command reads `*_gear.json` files from the extracted archive, maps Garmin gear types to FitTrackee equipment types, and creates or updates equipment accordingly.

#### Equipment type mapping

The default mapping (in `equipment_mapping.toml`) maps:

| Garmin type | FitTrackee type |
|---|---|
| Bike | Bike |
| Shoes | Shoe |

Unmapped Garmin gear types (e.g. "Other") are skipped with a warning. To customize the mapping, provide a `--mapping-file` with a `[gear_type_mapping]` TOML section.

### Sync activities to FitTrackee

```bash
uv run garmin2fittrackee sync-activities <path_to_extracted_archive_or_zip> [OPTIONS]
```

Options:
- `--fittrackee-url <url>` — FitTrackee instance URL (env: `FITTRACKEE_URL`)
- `--username <user>` — FitTrackee username (env: `FITTRACKEE_USERNAME`)
- `--password <pass>` — FitTrackee password (env: `FITTRACKEE_PASSWORD`)
- `--activity-mapping-file <path>` — Custom activity type TOML mapping file (default: built-in)
- `--dry-run` — Show what would be synced without making changes

The command reads `*_summarizedActivities.json` files from the extracted archive, maps Garmin activity types to FitTrackee sports, and creates workouts via the FitTrackee API. Activities already present (matched by start time ±10 seconds) are skipped.

A progress bar with live counters and ETA is displayed during sync, showing `(+N created  ↻N updated  ⏭N skipped  ✗N errors)  processed / total` with color-coded counters (green/blue/grey/red). If matching GPX files are found in `DI_CONNECT/DI-Connect-Uploaded-Files/`, the original file is uploaded to FitTrackee for richer data.

#### Activity type mapping

The default mapping (in `activity_mapping.toml`) maps:

| Garmin activity type | FitTrackee sport |
|---|---|
| running | Running |
| cycling | Cycling (Sport) |
| mountain_biking | Mountain Biking |
| hiking | Hiking |
| walking | Walking |
| treadmill_running | Running |
| road_biking | Cycling (Sport) |
| trail_running | Trail |
| indoor_cycling | Cycling (Sport) |
| cycling_transport | Cycling (Transport) |
| elliptical | Other |
| swimming | Other |
| yoga | Other |
| strength_training | Other |
| resort_skiing | Skiing (Alpine) |
| resort_skiing_snowboarding_ws | Skiing (Alpine) |
| stand_up_paddleboarding_v2 | Standup Paddleboarding |
| open_water_swimming | Open Water Swimming |
| inline_skating | Inline Skating |
| kayaking_v2 | Canoeing |
| rowing_v2 | Canoeing |

Unmapped Garmin activity types are skipped with a warning. To customize the mapping, provide an `--activity-mapping-file` with an `[activity_type_mapping]` TOML section.

### Others
#### Delete all equipments

Utility script to remove all equipments from a FitTrackee instance:

```bash
FITTRACKEE_URL=https://fittrackee.example.com \
FITTRACKEE_USERNAME=user@example.com \
FITTRACKEE_PASSWORD=secret \
  ./scripts/delete_all_equipments.sh
```

Requires `curl` and `jq`. Forces deletion even if equipments have associated workouts.


#### Delete all activities

Utility script to remove all workouts from a FitTrackee instance:
```bash
FITTRACKEE_URL=https://fittrackee.example.com \
FITTRACKEE_USERNAME=user@example.com \
FITTRACKEE_PASSWORD=secret \
  ./scripts/delete_all_activities.sh
```
Requires `curl` and `jq`. Paginates through all workouts and deletes them one by one.

## Known Issues
1. **Workout upload fails with "invalid format for workout date"** — Some activities fail to upload with an HTTP 500 error reporting an invalid date format.

2. **Workout upload fails with "invalid ascent or descent"** — Activities with elevation data (skiing, treadmill with incline, training plans) fail to upload due to FitTrackee rejecting negative or inconsistent ascent/descent values.

3. **Workout upload fails when FIT file exceeds FitTrackee size limit** — Large FIT files (>1MB) from long activities (e.g., trail runs) are rejected with HTTP 413. The workout is not created at all.

4. **Workout upload fails for activities without GPS data** — Activities recorded without GPS (indoor workouts, treadmill runs) fail with "no valid segments with GPS found in fit file". The tool should fall back to creating the workout without a trace file.

5. **Workout upload fails with "only one piece of equipment per type"** — Activities associated with multiple equipment items of the same type (e.g., two pairs of shoes) are rejected by FitTrackee. The tool should send at most one equipment item per type.

6. **Workout upload fails when equipment is inactive** — Workouts fail to create when the associated equipment is marked as inactive in FitTrackee. The tool should handle inactive equipment gracefully (skip or warn).

7. **Mismatch in duration, distance, and max speed** — Synced activities may show incorrect values for duration, distance, max speed, and other metrics compared to the original Garmin data. FitTrackee may rebuild it from .gpx, .tcx and .fit files with some variations compared to Garmin.

## Development

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest --cov=src --cov-report=term -v
```

## Links
### FitTrackee
https://docs.fittrackee.org/
https://codeberg.org/FitTrackee/FitTrackee

### Requesting Garmin data export
https://www.garmin.com/fr-FR/account/datamanagement/exportdata
