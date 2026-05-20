import logging
import struct
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from garmin2fittrackee import GearError
from garmin2fittrackee.converter import (
    ActivitySyncResult,
    EquipmentSyncResult,
    _build_description,
    _format_activity_counters,
    _format_equipment_counters,
    _format_workout_date,
    check_duplicate_labels,
    convert_activity,
    convert_gear,
    find_duplicate,
    resolve_equipment_ids,
    sync_activities,
    sync_equipments,
)
from garmin2fittrackee.fittrackee.models import (
    FitTrackeeEquipment,
    FitTrackeeEquipmentType,
    FitTrackeeSport,
    FitTrackeeWorkout,
)
from garmin2fittrackee.garmin.activities import GarminActivity
from garmin2fittrackee.garmin.gear import GarminGear

FT_TYPES = [
    FitTrackeeEquipmentType(id=1, label="Shoe", is_active=True),
    FitTrackeeEquipmentType(id=2, label="Bike", is_active=True),
]
MAPPING = {"Shoes": "Shoe", "Bike": "Bike"}


def _gear(
    pk: int = 1,
    type_name: str = "Shoes",
    status: str = "active",
    model: str = "Test Shoes",
    display_name: str | None = None,
) -> GarminGear:
    return GarminGear(
        gearPk=pk,
        uuid="test-uuid",
        userProfilePk=1,
        gearTypeName=type_name,
        gearStatusName=status,
        customMakeModel=model,
        displayName=display_name,
        dateBegin="2020-01-01",
        dateEnd=None,
        maximumMeters=500000.0,
        notified=False,
        gearVersion=0,
        createDate="2020-01-01",
        updateDate="2020-01-01",
    )


def _ft_equipment(
    label: str = "Test Shoes",
    type_id: int = 1,
    is_active: bool = True,
    description: str | None = None,
) -> FitTrackeeEquipment:
    return FitTrackeeEquipment(
        id="ft-123",
        label=label,
        is_active=is_active,
        description=description,
        creation_date="Tue, 21 Mar 2023 06:08:06 GMT",
        equipment_type=FitTrackeeEquipmentType(
            id=type_id,
            label="Shoe" if type_id == 1 else "Bike",
            is_active=True,
        ),
    )


class TestConvertGear:
    def test_convert_active_shoes(self) -> None:
        gear = _gear()
        result = convert_gear(gear, MAPPING, FT_TYPES)
        assert result is not None
        assert result.label == "Test Shoes"
        assert result.equipment_type_id == 1
        assert result.is_active is True

    def test_convert_retired_shoes(self) -> None:
        gear = _gear(status="retired")
        result = convert_gear(gear, MAPPING, FT_TYPES)
        assert result is not None
        assert result.is_active is False

    def test_convert_unmapped_type_returns_none(self) -> None:
        gear = _gear(type_name="Other")
        result = convert_gear(gear, MAPPING, FT_TYPES)
        assert result is None

    def test_convert_bike(self) -> None:
        gear = _gear(type_name="Bike", model="Canyon")
        result = convert_gear(gear, MAPPING, FT_TYPES)
        assert result is not None
        assert result.equipment_type_id == 2


class TestCheckDuplicateLabels:
    def test_no_duplicates(self) -> None:
        gears = [_gear(pk=1, model="Shoe A"), _gear(pk=2, model="Shoe B")]
        check_duplicate_labels(gears)

    def test_duplicates_raise(self) -> None:
        gears = [_gear(pk=1, model="Same"), _gear(pk=2, model="Same")]
        with pytest.raises(GearError, match="Duplicate gear labels"):
            check_duplicate_labels(gears)


class TestSyncEquipments:
    def test_creates_new_equipment(self) -> None:
        client = MagicMock()
        client.get_equipments.return_value = []
        client.create_equipment.return_value = _ft_equipment()

        gears = [_gear()]
        result = sync_equipments(gears, client, MAPPING, FT_TYPES)
        assert isinstance(result, EquipmentSyncResult)
        assert result.created == 1
        client.create_equipment.assert_called_once()

    def test_skips_identical_equipment(self) -> None:
        existing = _ft_equipment(
            description="Synced from Garmin (original type: Shoes)"
        )
        client = MagicMock()
        client.get_equipments.return_value = [existing]

        gears = [_gear()]
        result = sync_equipments(gears, client, MAPPING, FT_TYPES)
        assert isinstance(result, EquipmentSyncResult)
        assert result.skipped == 1
        assert result.created == 0
        client.create_equipment.assert_not_called()
        client.update_equipment.assert_not_called()

    def test_updates_changed_equipment(self) -> None:
        existing = _ft_equipment(
            description="Synced from Garmin (original type: Shoes)",
            is_active=True,
        )
        client = MagicMock()
        client.get_equipments.return_value = [existing]
        client.update_equipment.return_value = existing

        gears = [_gear(status="retired")]
        result = sync_equipments(gears, client, MAPPING, FT_TYPES)
        assert isinstance(result, EquipmentSyncResult)
        assert result.updated == 1
        client.update_equipment.assert_called_once()

    def test_skips_unmapped_types(self) -> None:
        client = MagicMock()
        client.get_equipments.return_value = []

        gears = [_gear(type_name="Other")]
        result = sync_equipments(gears, client, MAPPING, FT_TYPES)
        assert isinstance(result, EquipmentSyncResult)
        assert result.unmapped == 1
        client.create_equipment.assert_not_called()

    def test_dry_run_does_not_call_api(self) -> None:
        client = MagicMock()

        gears = [_gear()]
        result = sync_equipments(gears, client, MAPPING, FT_TYPES, dry_run=True)
        assert isinstance(result, EquipmentSyncResult)
        assert result.created == 1
        client.get_equipments.assert_not_called()
        client.create_equipment.assert_not_called()
        client.update_equipment.assert_not_called()

    def test_duplicate_labels_stops_sync(self) -> None:
        client = MagicMock()
        gears = [_gear(pk=1, model="Same"), _gear(pk=2, model="Same")]
        with pytest.raises(GearError, match="Duplicate gear labels"):
            sync_equipments(gears, client, MAPPING, FT_TYPES)

    def test_force_active_overrides_retired_status(self) -> None:
        client = MagicMock()
        client.get_equipments.return_value = []
        client.create_equipment.return_value = _ft_equipment()

        gears = [_gear(status="retired")]
        result = sync_equipments(
            gears, client, MAPPING, FT_TYPES, force_active=True
        )
        assert result.created == 1
        create_arg = client.create_equipment.call_args[0][0]
        assert create_arg.is_active is True

    def test_force_active_on_update(self) -> None:
        existing = _ft_equipment(
            description="Synced from Garmin (original type: Shoes)",
            is_active=False,
        )
        client = MagicMock()
        client.get_equipments.return_value = [existing]
        client.update_equipment.return_value = existing

        gears = [_gear(status="retired")]
        result = sync_equipments(
            gears, client, MAPPING, FT_TYPES, force_active=True
        )
        assert result.updated == 1
        patch = client.update_equipment.call_args[0][1]
        assert patch.is_active is True

    def test_force_active_no_change_when_already_active(self) -> None:
        existing = _ft_equipment(
            description="Synced from Garmin (original type: Shoes)",
            is_active=True,
        )
        client = MagicMock()
        client.get_equipments.return_value = [existing]

        gears = [_gear(status="active")]
        result = sync_equipments(
            gears, client, MAPPING, FT_TYPES, force_active=True
        )
        assert result.skipped == 1
        client.update_equipment.assert_not_called()


class TestReSyncEquipments:
    def test_recreates_deleted_equipment(self) -> None:
        trail = _gear(pk=1, model="Trail Shoes")
        road = _gear(pk=2, model="Road Shoes")

        client = MagicMock()

        existing_road = _ft_equipment(
            label="Road Shoes",
            description="Synced from Garmin (original type: Shoes)",
        )
        client.get_equipments.return_value = [existing_road]
        client.create_equipment.return_value = _ft_equipment(label="Trail Shoes")

        sync_equipments([trail, road], client, MAPPING, FT_TYPES)

        client.create_equipment.assert_called_once()
        assert client.create_equipment.call_args[0][0].label == "Trail Shoes"
        client.update_equipment.assert_not_called()

    def test_updates_altered_description(self) -> None:
        gear = _gear(pk=1, model="Trail Shoes")

        client = MagicMock()
        existing = _ft_equipment(
            label="Trail Shoes",
            description="User edited this description",
        )
        client.get_equipments.return_value = [existing]
        client.update_equipment.return_value = existing

        sync_equipments([gear], client, MAPPING, FT_TYPES)

        client.create_equipment.assert_not_called()
        client.update_equipment.assert_called_once()
        patch = client.update_equipment.call_args[0][1]
        assert patch.description == "Synced from Garmin (original type: Shoes)"

    def test_updates_altered_is_active(self) -> None:
        gear = _gear(pk=1, model="Trail Shoes", status="retired")

        client = MagicMock()
        existing = _ft_equipment(
            label="Trail Shoes",
            is_active=True,
            description="Synced from Garmin (original type: Shoes)",
        )
        client.get_equipments.return_value = [existing]
        client.update_equipment.return_value = existing

        sync_equipments([gear], client, MAPPING, FT_TYPES)

        client.update_equipment.assert_called_once()
        patch = client.update_equipment.call_args[0][1]
        assert patch.is_active is False

    def test_updates_altered_equipment_type(self) -> None:
        gear = _gear(pk=1, model="Trail Shoes", type_name="Bike")

        client = MagicMock()
        existing = _ft_equipment(
            label="Trail Shoes",
            type_id=1,
            description="Synced from Garmin (original type: Bike)",
        )
        client.get_equipments.return_value = [existing]
        client.update_equipment.return_value = existing

        sync_equipments([gear], client, MAPPING, FT_TYPES)

        client.update_equipment.assert_called_once()
        patch = client.update_equipment.call_args[0][1]
        assert patch.equipment_type_id == 2

    def test_no_changes_when_identical_after_resync(self) -> None:
        gear = _gear(pk=1, model="Trail Shoes")

        client = MagicMock()
        existing = _ft_equipment(
            label="Trail Shoes",
            description="Synced from Garmin (original type: Shoes)",
        )
        client.get_equipments.return_value = [existing]

        sync_equipments([gear], client, MAPPING, FT_TYPES)

        client.create_equipment.assert_not_called()
        client.update_equipment.assert_not_called()


def _activity(
    activity_id: int = 123,
    type_key: str = "running",
    start_local: str = "2024-01-15 08:00:00",
    duration: float = 1800.0,
    distance: float = 5000.0,
    title: str | None = None,
    elevation_gain: float = 0.0,
    elevation_loss: float = 0.0,
    device_product_name: str | None = None,
) -> GarminActivity:
    return GarminActivity(
        activityId=activity_id,
        activityType={"typeKey": type_key},
        startTimeLocal=start_local,
        startTimeGMT="2024-01-15 07:00:00",
        durationInSeconds=duration,
        distanceInMeters=distance,
        elevationGainInMeters=elevation_gain,
        elevationLossInMeters=elevation_loss,
        title=title,
        deviceProductName=device_product_name,
    )


SPORTS = [
    FitTrackeeSport(id=5, label="Running", is_active=True),
    FitTrackeeSport(id=1, label="Cycling (Sport)", is_active=True),
]
ACTIVITY_MAPPING = {"running": "Running", "cycling": "Cycling (Sport)"}


class TestFormatWorkoutDate:
    def test_strips_seconds_from_standard_format(self) -> None:
        assert _format_workout_date("2024-01-15 08:00:00") == "2024-01-15 08:00"

    def test_handles_iso_format(self) -> None:
        assert _format_workout_date("2024-01-15T08:00:00") == "2024-01-15 08:00"

    def test_already_no_seconds_truncates(self) -> None:
        assert _format_workout_date("2024-01-15 08:00") == "2024-01-15 08:00"

    def test_unknown_format_truncates_to_16_chars(self) -> None:
        assert _format_workout_date("2024/01/15 08:00") == "2024/01/15 08:00"

    def test_short_string_passed_through(self) -> None:
        assert _format_workout_date("2024-01-15") == "2024-01-15"


class TestConvertActivity:
    def test_convert_running(self) -> None:
        activity = _activity()
        result = convert_activity(activity, sport_id=5)
        assert result.sport_id == 5
        assert result.duration == 1800
        assert result.distance == 5.0
        assert result.workout_date == "2024-01-15 08:00"
        assert result.equipment_ids is None

    def test_convert_with_title(self) -> None:
        activity = _activity(title="Morning Run")
        result = convert_activity(activity, sport_id=5)
        assert result.title == "Morning Run"

    def test_convert_with_elevation(self) -> None:
        activity = _activity(elevation_gain=100.0, elevation_loss=80.0)
        result = convert_activity(activity, sport_id=5)
        assert result.ascent == 100.0
        assert result.descent == 80.0

    def test_convert_zero_elevation_is_none(self) -> None:
        activity = _activity(elevation_gain=0.0, elevation_loss=0.0)
        result = convert_activity(activity, sport_id=5)
        assert result.ascent is None
        assert result.descent is None

    def test_convert_with_equipment_ids(self) -> None:
        activity = _activity()
        result = convert_activity(activity, sport_id=5, equipment_ids=["eq1", "eq2"])
        assert result.equipment_ids == ["eq1", "eq2"]

    def test_convert_with_empty_equipment_ids(self) -> None:
        activity = _activity()
        result = convert_activity(activity, sport_id=5, equipment_ids=[])
        assert result.equipment_ids == []


class TestResolveEquipmentIds:
    def test_resolves_known_equipment(self) -> None:
        gear_mapping = {123: [100]}
        gear_by_pk = {100: _gear(pk=100, model="Trail Shoes")}
        ft_eqs = {
            "Trail Shoes": FitTrackeeEquipment(
                id="ft-1",
                label="Trail Shoes",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        result = resolve_equipment_ids(123, gear_mapping, gear_by_pk, ft_eqs)
        assert result == ["ft-1"]

    def test_resolves_multiple_equipment(self) -> None:
        gear_mapping = {123: [100, 200]}
        gear_by_pk = {
            100: _gear(pk=100, model="Trail Shoes"),
            200: _gear(pk=200, type_name="Bike", model="Road Bike"),
        }
        ft_eqs = {
            "Trail Shoes": FitTrackeeEquipment(
                id="ft-1",
                label="Trail Shoes",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
            "Road Bike": FitTrackeeEquipment(
                id="ft-2",
                label="Road Bike",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=2, label="Bike", is_active=True
                ),
            ),
        }
        result = resolve_equipment_ids(123, gear_mapping, gear_by_pk, ft_eqs)
        assert result == ["ft-1", "ft-2"]

    def test_warns_on_missing_equipment(self) -> None:
        gear_mapping = {123: [100]}
        gear_by_pk = {100: _gear(pk=100, model="Unknown Shoes")}
        result = resolve_equipment_ids(123, gear_mapping, gear_by_pk, {})
        assert result == []

    def test_no_gear_for_activity(self) -> None:
        result = resolve_equipment_ids(123, {}, {}, {})
        assert result == []

    def test_partial_resolution(self) -> None:
        gear_mapping = {123: [100, 200]}
        gear_by_pk = {
            100: _gear(pk=100, model="Trail Shoes"),
            200: _gear(pk=200, model="Unknown Bike"),
        }
        ft_eqs = {
            "Trail Shoes": FitTrackeeEquipment(
                id="ft-1",
                label="Trail Shoes",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        result = resolve_equipment_ids(123, gear_mapping, gear_by_pk, ft_eqs)
        assert result == ["ft-1"]

    def test_gear_pk_not_in_definitions(self) -> None:
        gear_mapping = {123: [999]}
        gear_by_pk: dict[int, GarminGear] = {}
        result = resolve_equipment_ids(123, gear_mapping, gear_by_pk, {})
        assert result == []


class TestFindDuplicate:
    def test_exact_match(self) -> None:
        workouts = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
            )
        ]
        dt = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        result = find_duplicate(dt, workouts)
        assert result is not None
        assert result.id == "w1"

    def test_within_margin(self) -> None:
        workouts = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:05",
                duration="0:30:00",
            )
        ]
        dt = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        result = find_duplicate(dt, workouts)
        assert result is not None
        assert result.id == "w1"

    def test_outside_margin(self) -> None:
        workouts = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:30",
                duration="0:30:00",
            )
        ]
        dt = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        assert find_duplicate(dt, workouts) is None

    def test_no_workouts(self) -> None:
        dt = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        assert find_duplicate(dt, []) is None


class TestSyncActivities:
    def test_creates_new_activity(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new1", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {}
        )
        assert isinstance(result, ActivitySyncResult)
        assert result.created == 1
        client.create_workout_no_gpx.assert_called_once()

    def test_skips_duplicate_no_changes(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Morning Run",
                description="Synced from Garmin (type: running)",
                equipment_ids=None,
            )
        ]

        activities = [_activity(title="Morning Run")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {}
        )
        assert isinstance(result, ActivitySyncResult)
        assert result.skipped == 1
        assert result.created == 0
        assert result.updated == 0
        client.create_workout_no_gpx.assert_not_called()
        client.update_workout.assert_not_called()

    def test_patches_title_on_duplicate(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Old Title",
                description="Synced from Garmin (type: running)",
            )
        ]
        client.update_workout.return_value = FitTrackeeWorkout(
            id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
            duration="0:30:00", title="New Title",
        )

        activities = [_activity(title="New Title")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {}
        )
        assert result.updated == 1
        assert result.skipped == 0
        assert result.created == 0
        client.update_workout.assert_called_once()
        patch = client.update_workout.call_args[0][1]
        assert patch.title == "New Title"

    def test_patches_description_on_duplicate(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Morning Run",
                description="Old description",
            )
        ]
        client.update_workout.return_value = FitTrackeeWorkout(
            id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
            duration="0:30:00", title="Morning Run",
        )

        activities = [_activity(title="Morning Run")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {}
        )
        assert result.updated == 1
        client.update_workout.assert_called_once()
        patch = client.update_workout.call_args[0][1]
        assert patch.description == "Synced from Garmin (type: running)"

    def test_patches_equipment_on_duplicate(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Morning Run",
                description="Synced from Garmin (type: running)",
                equipment_ids=None,
            )
        ]
        client.update_workout.return_value = FitTrackeeWorkout(
            id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
            duration="0:30:00", title="Morning Run",
        )

        ft_eqs = {
            "Trail Shoes": FitTrackeeEquipment(
                id="ft-1",
                label="Trail Shoes",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        gm: dict[int, list[int]] = {123: [100]}
        gb: dict[int, GarminGear] = {
            100: _gear(pk=100, model="Trail Shoes"),
        }

        activities = [_activity(title="Morning Run")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            ft_equipments=ft_eqs, gear_mapping=gm, gear_by_pk=gb,
        )
        assert result.updated == 1
        client.update_workout.assert_called_once()
        patch = client.update_workout.call_args[0][1]
        assert patch.equipment_ids == ["ft-1"]

    def test_patches_equipment_changed_on_duplicate(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Morning Run",
                description="Synced from Garmin (type: running)",
                equipment_ids=["old-eq"],
            )
        ]
        client.update_workout.return_value = FitTrackeeWorkout(
            id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
            duration="0:30:00", title="Morning Run",
        )

        ft_eqs = {
            "Trail Shoes": FitTrackeeEquipment(
                id="ft-1",
                label="Trail Shoes",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        gm: dict[int, list[int]] = {123: [100]}
        gb: dict[int, GarminGear] = {
            100: _gear(pk=100, model="Trail Shoes"),
        }

        activities = [_activity(title="Morning Run")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            ft_equipments=ft_eqs, gear_mapping=gm, gear_by_pk=gb,
        )
        assert result.updated == 1
        patch = client.update_workout.call_args[0][1]
        assert patch.equipment_ids == ["ft-1"]

    def test_no_patch_when_equipment_identical(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Morning Run",
                description="Synced from Garmin (type: running)",
                equipment_ids=["ft-1"],
            )
        ]

        ft_eqs = {
            "Trail Shoes": FitTrackeeEquipment(
                id="ft-1",
                label="Trail Shoes",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        gm: dict[int, list[int]] = {123: [100]}
        gb: dict[int, GarminGear] = {
            100: _gear(pk=100, model="Trail Shoes"),
        }

        activities = [_activity(title="Morning Run")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            ft_equipments=ft_eqs, gear_mapping=gm, gear_by_pk=gb,
        )
        assert result.skipped == 1
        assert result.updated == 0
        client.update_workout.assert_not_called()

    def test_update_error_counted(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Old Title",
                description="Synced from Garmin (type: running)",
            )
        ]
        client.update_workout.side_effect = Exception("API error")

        activities = [_activity(title="New Title")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {}
        )
        assert result.errors == 1
        assert result.updated == 0

    def test_skips_unmapped_type(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []

        activities = [_activity(type_key="unknown")]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {}
        )
        assert isinstance(result, ActivitySyncResult)
        assert result.unmapped == 1
        client.create_workout_no_gpx.assert_not_called()

    def test_dry_run_does_not_call_api(self) -> None:
        client = MagicMock()

        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            dry_run=True,
        )
        assert isinstance(result, ActivitySyncResult)
        assert result.created == 1
        client.get_all_workouts.assert_not_called()
        client.create_workout_no_gpx.assert_not_called()

    def test_multiple_activities(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        activities = [
            _activity(activity_id=1, start_local="2024-01-15 08:00:00"),
            _activity(activity_id=2, start_local="2024-01-16 08:00:00"),
        ]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {}
        )
        assert result.created == 2
        assert client.create_workout_no_gpx.call_count == 2

    def test_with_gpx_only_skips_no_file(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            with_gpx_only=True,
        )
        client.create_workout_no_gpx.assert_not_called()
        client.create_workout_with_file.assert_not_called()

    def test_with_gpx_only_creates_with_file(self) -> None:
        from datetime import datetime, timezone
        from pathlib import Path

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        gpx_path = Path("/fake/file.gpx")
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            with_gpx_only=True,
        )
        client.create_workout_with_file.assert_called_once()
        client.create_workout_no_gpx.assert_not_called()

    def test_with_gpx_only_skips_no_gps_data(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="0.0" lon="0.0"><time>2024-01-15T07:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "no_gps.gpx"
        gpx_path.write_text(gpx)

        client = MagicMock()
        client.get_all_workouts.return_value = []

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            with_gpx_only=True,
        )
        client.create_workout_with_file.assert_not_called()
        client.create_workout_no_gpx.assert_not_called()

    def test_with_gpx_only_creates_with_gps_data(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="48.8566" lon="2.3522"><time>2024-01-15T07:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "with_gps.gpx"
        gpx_path.write_text(gpx)

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            with_gpx_only=True,
        )
        client.create_workout_with_file.assert_called_once()

    def test_without_gpx_only_creates_no_gps_file(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="0.0" lon="0.0"><time>2024-01-15T07:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "no_gps.gpx"
        gpx_path.write_text(gpx)

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            with_gpx_only=False,
        )
        client.create_workout_with_file.assert_called_once()


class TestSyncActivitiesWithEquipment:
    def _make_gear_context(
        self, activity_id: int = 123, gear_pks: list[int] | None = None
    ) -> tuple[dict[int, list[int]], dict[int, GarminGear]]:
        gm: dict[int, list[int]] = {}
        gb: dict[int, GarminGear] = {}
        if gear_pks:
            gm[activity_id] = gear_pks
            for pk in gear_pks:
                gb[pk] = _gear(pk=pk, model=f"Gear-{pk}")
        return gm, gb

    def test_links_equipment_to_workout(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        ft_eqs = {
            "Gear-100": FitTrackeeEquipment(
                id="ft-1",
                label="Gear-100",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        gm, gb = self._make_gear_context(gear_pks=[100])

        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            ft_equipments=ft_eqs, gear_mapping=gm, gear_by_pk=gb,
        )
        assert result.created == 1
        call_args = client.create_workout_no_gpx.call_args[0][0]
        assert call_args.equipment_ids == ["ft-1"]

    def test_logs_warning_for_missing_equipment(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        gm, gb = self._make_gear_context(gear_pks=[100])
        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            ft_equipments={}, gear_mapping=gm, gear_by_pk=gb,
        )
        assert result.created == 1
        call_args = client.create_workout_no_gpx.call_args[0][0]
        assert call_args.equipment_ids is None

    def test_no_equipment_when_activity_has_no_gear(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        ft_eqs = {
            "Gear-100": FitTrackeeEquipment(
                id="ft-1",
                label="Gear-100",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }

        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            ft_equipments=ft_eqs, gear_mapping={}, gear_by_pk={},
        )
        assert result.created == 1
        call_args = client.create_workout_no_gpx.call_args[0][0]
        assert call_args.equipment_ids is None

    def test_links_equipment_with_file(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="48.8566" lon="2.3522"><time>2024-01-15T07:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "test.gpx"
        gpx_path.write_text(gpx)

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: gpx_path}

        ft_eqs = {
            "Gear-100": FitTrackeeEquipment(
                id="ft-1",
                label="Gear-100",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        gm, gb = self._make_gear_context(gear_pks=[100])

        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            with_gpx_only=True,
            ft_equipments=ft_eqs, gear_mapping=gm, gear_by_pk=gb,
        )
        assert result.created == 1
        call_args = client.create_workout_with_file.call_args[0][0]
        assert call_args.equipment_ids == ["ft-1"]

    def test_dry_run_resolves_equipment(self) -> None:
        client = MagicMock()

        ft_eqs = {
            "Gear-100": FitTrackeeEquipment(
                id="ft-1",
                label="Gear-100",
                is_active=True,
                equipment_type=FitTrackeeEquipmentType(
                    id=1, label="Shoe", is_active=True
                ),
            ),
        }
        gm, gb = self._make_gear_context(gear_pks=[100])

        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
            dry_run=True,
            ft_equipments=ft_eqs, gear_mapping=gm, gear_by_pk=gb,
        )
        assert result.created == 1
        client.create_workout_no_gpx.assert_not_called()

    def test_backward_compat_no_ft_equipments(self) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        activities = [_activity()]
        result = sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, {},
        )
        assert result.created == 1
        call_args = client.create_workout_no_gpx.call_args[0][0]
        assert call_args.equipment_ids is None


def _build_fit_without_gps() -> bytes:
    header = bytearray(14)
    header[0] = 14
    header[1] = 16
    struct.pack_into("<H", header, 2, 0)
    header[8:12] = b".FIT"
    records = bytearray()
    def_hdr = bytearray()
    def_hdr.append(0x40)
    def_hdr.append(0)
    def_hdr.append(0)
    def_hdr.extend(struct.pack("<H", 20))
    def_hdr.append(1)
    def_hdr.append(253)
    def_hdr.append(4)
    def_hdr.append(0x86)
    records.extend(def_hdr)
    data_rec = bytearray()
    data_rec.append(0x00)
    data_rec.extend(struct.pack("<I", 0))
    records.extend(data_rec)
    struct.pack_into("<I", header, 4, len(records))
    return bytes(header) + bytes(records) + b"\x00\x00"


class TestSyncActivitiesFitNoGps:
    def test_fit_no_gps_skipped_with_gpx_only(self, tmp_path: Path) -> None:
        fit_path = tmp_path / "treadmill.fit"
        fit_path.write_bytes(_build_fit_without_gps())

        client = MagicMock()
        client.get_all_workouts.return_value = []

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: fit_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            with_gpx_only=True,
        )
        client.create_workout_with_file.assert_not_called()
        client.create_workout_no_gpx.assert_not_called()


def _build_fit_with_gps() -> bytes:
    header = bytearray(14)
    header[0] = 14
    header[1] = 16
    struct.pack_into("<H", header, 2, 0)
    header[8:12] = b".FIT"
    records = bytearray()
    def_hdr = bytearray()
    def_hdr.append(0x40)
    def_hdr.append(0)
    def_hdr.append(0)
    def_hdr.extend(struct.pack("<H", 20))
    def_hdr.append(2)
    def_hdr.extend([0, 4, 0x86])
    def_hdr.extend([1, 4, 0x86])
    records.extend(def_hdr)
    data_rec = bytearray()
    data_rec.append(0x00)
    data_rec.extend(struct.pack("<i", 600000000))
    data_rec.extend(struct.pack("<i", 200000000))
    records.extend(data_rec)
    struct.pack_into("<I", header, 4, len(records))
    return bytes(header) + bytes(records) + b"\x00\x00"


class TestSyncActivitiesFitWithGps:
    def test_fit_with_gps_uploaded_with_flag(self, tmp_path: Path) -> None:
        fit_path = tmp_path / "activity.fit"
        fit_path.write_bytes(_build_fit_with_gps())

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: fit_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            with_gpx_only=True,
        )
        client.create_workout_with_file.assert_called_once()
        client.create_workout_no_gpx.assert_not_called()

    def test_fit_with_gps_uploaded_without_flag(self, tmp_path: Path) -> None:
        fit_path = tmp_path / "activity.fit"
        fit_path.write_bytes(_build_fit_with_gps())

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: fit_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
        )
        client.create_workout_with_file.assert_called_once()
        client.create_workout_no_gpx.assert_not_called()


class TestBuildDescription:
    def test_without_device(self) -> None:
        activity = _activity()
        desc = _build_description(activity)
        assert desc == "Synced from Garmin (type: running)"

    def test_with_device(self) -> None:
        activity = _activity(device_product_name="Garmin fenix 7")
        desc = _build_description(activity)
        assert "Synced from Garmin (type: running)" in desc
        assert "Device: Garmin fenix 7" in desc

    def test_description_separator(self) -> None:
        activity = _activity(device_product_name="Forerunner 265")
        desc = _build_description(activity)
        assert desc == (
            "Synced from Garmin (type: running) | Device: Forerunner 265"
        )


class TestConvertActivityWithDevice:
    def test_description_includes_device(self) -> None:
        activity = _activity(device_product_name="Garmin fenix 7")
        result = convert_activity(activity, sport_id=5)
        assert "Device: Garmin fenix 7" in result.description

    def test_description_without_device(self) -> None:
        activity = _activity()
        result = convert_activity(activity, sport_id=5)
        assert result.description == "Synced from Garmin (type: running)"
        assert "Device:" not in result.description


class TestSyncActivitiesGpxPatch:
    def test_patches_gpx_creator_with_device_name(
        self, tmp_path: Path
    ) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="wrong_device">
  <trk><trkseg>
    <trkpt lat="48.8566" lon="2.3522"><time>2024-01-15T07:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "original" / "run.gpx"
        gpx_path.parent.mkdir(parents=True)
        gpx_path.write_text(gpx)

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity(device_product_name="Garmin fenix 7")]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
        )

        assert client.create_workout_with_file.call_count == 1
        uploaded_path = client.create_workout_with_file.call_args[0][1]
        assert "wrong_device" not in Path(uploaded_path).read_text()
        assert "Garmin fenix 7" in Path(uploaded_path).read_text()

    def test_does_not_patch_fit_file(self, tmp_path: Path) -> None:
        fit_path = tmp_path / "activity.fit"
        fit_path.write_bytes(_build_fit_with_gps())

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: fit_path}

        activities = [_activity(device_product_name="UnknownDevice")]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
        )

        assert client.create_workout_with_file.call_count == 1
        uploaded_path = client.create_workout_with_file.call_args[0][1]
        assert uploaded_path == str(fit_path)

    def test_no_patch_without_device_name(self, tmp_path: Path) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="original">
  <trk><trkseg>
    <trkpt lat="48.8566" lon="2.3522"><time>2024-01-15T07:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "run.gpx"
        gpx_path.write_text(gpx)

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
        )

        assert client.create_workout_with_file.call_count == 1
        uploaded_path = client.create_workout_with_file.call_args[0][1]
        assert uploaded_path == str(gpx_path)


class TestSyncActivitiesTcxPatch:
    def test_patches_tcx_creator_with_device_name(
        self, tmp_path: Path
    ) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2024-01-15T07:00:00.000Z</Id>
      <Creator><Name>Wrong Device</Name></Creator>
      <Lap StartTime="2024-01-15T07:00:00.000Z">
        <Track>
          <Trackpoint>
            <Time>2024-01-15T07:00:00.000Z</Time>
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

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: tcx_path}

        activities = [_activity(device_product_name="Garmin fenix 7")]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
        )

        assert client.create_workout_with_file.call_count == 1
        uploaded_path = client.create_workout_with_file.call_args[0][1]
        content = Path(uploaded_path).read_text()
        assert "Wrong Device" not in content
        assert "Garmin fenix 7" in content

    def test_no_patch_without_device_name(self, tmp_path: Path) -> None:
        tcx = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2024-01-15T07:00:00.000Z</Id>
      <Creator><Name>Original</Name></Creator>
      <Lap><Track></Track></Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
        tcx_path = tmp_path / "run.tcx"
        tcx_path.write_text(tcx)

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: tcx_path}

        activities = [_activity()]
        sync_activities(
            activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
        )

        assert client.create_workout_with_file.call_count == 1
        uploaded_path = client.create_workout_with_file.call_args[0][1]
        assert uploaded_path == str(tcx_path)


class TestFormatActivityCounters:
    def test_all_zero(self) -> None:
        result = _format_activity_counters(0, 0, 0, 0, 0, 100)
        assert "+0 created" in result
        assert "↻0 updated" in result
        assert "⏭0 skipped" in result
        assert "✗0 errors" in result
        assert "0 / 100" in result

    def test_nonzero_values(self) -> None:
        result = _format_activity_counters(12, 3, 5, 1, 1, 50)
        assert "+12 created" in result
        assert "↻3 updated" in result
        assert "⏭5 skipped" in result
        assert "✗1 errors" in result
        assert "22 / 50" in result

    def test_processed_sum(self) -> None:
        result = _format_activity_counters(10, 2, 5, 3, 1, 30)
        assert "21 / 30" in result

    def test_parentheses(self) -> None:
        result = _format_activity_counters(1, 2, 3, 4, 5, 20)
        assert result.startswith("(")
        assert ")" in result

    def test_contains_rich_markup(self) -> None:
        result = _format_activity_counters(1, 2, 3, 4, 5, 10)
        assert "[green]" in result
        assert "[/green]" in result
        assert "[blue]" in result
        assert "[/blue]" in result
        assert "[grey]" in result
        assert "[/grey]" in result
        assert "[red]" in result
        assert "[/red]" in result

    def test_zero_total(self) -> None:
        result = _format_activity_counters(0, 0, 0, 0, 0, 0)
        assert "0 / 0" in result


class TestFormatEquipmentCounters:
    def test_all_zero(self) -> None:
        result = _format_equipment_counters(0, 0, 0, 0, 50)
        assert "+0 created" in result
        assert "↻0 updated" in result
        assert "⏭0 skipped" in result
        assert "?0 unmapped" in result
        assert "0 / 50" in result

    def test_nonzero_values(self) -> None:
        result = _format_equipment_counters(5, 2, 10, 1, 20)
        assert "+5 created" in result
        assert "↻2 updated" in result
        assert "⏭10 skipped" in result
        assert "?1 unmapped" in result
        assert "18 / 20" in result

    def test_processed_sum(self) -> None:
        result = _format_equipment_counters(3, 1, 4, 2, 15)
        assert "10 / 15" in result

    def test_parentheses(self) -> None:
        result = _format_equipment_counters(1, 2, 3, 4, 10)
        assert result.startswith("(")
        assert ")" in result

    def test_contains_rich_markup(self) -> None:
        result = _format_equipment_counters(1, 1, 1, 1, 10)
        assert "[green]" in result
        assert "[blue]" in result
        assert "[grey]" in result
        assert "[yellow]" in result

    def test_zero_total(self) -> None:
        result = _format_equipment_counters(0, 0, 0, 0, 0)
        assert "0 / 0" in result


class TestActivityMappingLogs:
    def test_logs_activity_to_file_mapping_with_file(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        gpx_path = Path("/fake/run.gpx")
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity(title="Morning Run")]
        with caplog.at_level(logging.INFO, logger="garmin2fittrackee.converter"):
            sync_activities(
                activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
            )

        mapping_msgs = [
            r for r in caplog.records if "-> file:" in r.message
        ]
        assert len(mapping_msgs) == 1
        assert "id=123" in mapping_msgs[0].message
        assert "Morning Run" in mapping_msgs[0].message
        assert "json_start_local=2024-01-15 08:00:00" in mapping_msgs[0].message
        assert "json_start_gmt=2024-01-15 07:00:00" in mapping_msgs[0].message
        assert "run.gpx" in mapping_msgs[0].message

    def test_logs_activity_to_file_mapping_no_file(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        activities = [_activity(title="No File Run")]
        with caplog.at_level(logging.INFO, logger="garmin2fittrackee.converter"):
            sync_activities(
                activities, client, ACTIVITY_MAPPING, SPORTS, {},
            )

        mapping_msgs = [r for r in caplog.records if "-> file:" in r.message]
        assert len(mapping_msgs) == 1
        assert "No File Run" in mapping_msgs[0].message
        assert "file: none" in mapping_msgs[0].message


class TestWorkoutDateLogs:
    def test_logs_workout_date_on_create(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_no_gpx.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        activities = [_activity()]
        with caplog.at_level(logging.INFO, logger="garmin2fittrackee.converter"):
            sync_activities(
                activities, client, ACTIVITY_MAPPING, SPORTS, {},
            )

        date_msgs = [r for r in caplog.records if "pushing workout_date=" in r.message]
        assert len(date_msgs) == 1
        assert "workout_date='2024-01-15 08:00'" in date_msgs[0].message
        assert "id=123" in date_msgs[0].message

    def test_logs_workout_date_on_update(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Old Title",
                description="Synced from Garmin (type: running)",
            )
        ]
        client.update_workout.return_value = FitTrackeeWorkout(
            id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
            duration="0:30:00", title="New Title",
        )

        activities = [_activity(title="New Title")]
        with caplog.at_level(logging.INFO, logger="garmin2fittrackee.converter"):
            sync_activities(
                activities, client, ACTIVITY_MAPPING, SPORTS, {},
            )

        date_msgs = [
            r
            for r in caplog.records
            if "pushing workout_date=" in r.message
            and "update" in r.message
        ]
        assert len(date_msgs) == 1
        assert "workout_date='2024-01-15 08:00'" in date_msgs[0].message
        assert "id=123" in date_msgs[0].message

    def test_logs_workout_date_on_duplicate_skip(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = MagicMock()
        client.get_all_workouts.return_value = [
            FitTrackeeWorkout(
                id="w1", sport_id=5, workout_date="2024-01-15 07:00:00",
                duration="0:30:00",
                title="Morning Run",
                description="Synced from Garmin (type: running)",
                equipment_ids=None,
            )
        ]

        activities = [_activity(title="Morning Run")]
        with caplog.at_level(logging.INFO, logger="garmin2fittrackee.converter"):
            sync_activities(
                activities, client, ACTIVITY_MAPPING, SPORTS, {},
            )

        date_msgs = [
            r
            for r in caplog.records
            if "pushing workout_date=" in r.message
            and "update" in r.message
        ]
        assert len(date_msgs) == 1
        assert "workout_date='2024-01-15 08:00'" in date_msgs[0].message

    def test_logs_workout_date_with_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="48.8566" lon="2.3522"><time>2024-01-15T07:00:00Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        gpx_path = tmp_path / "test.gpx"
        gpx_path.write_text(gpx)

        client = MagicMock()
        client.get_all_workouts.return_value = []
        client.create_workout_with_file.return_value = FitTrackeeWorkout(
            id="new", sport_id=5, workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
        )

        start = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        files_table: dict[datetime, Path] = {start: gpx_path}

        activities = [_activity()]
        with caplog.at_level(logging.INFO, logger="garmin2fittrackee.converter"):
            sync_activities(
                activities, client, ACTIVITY_MAPPING, SPORTS, files_table,
                with_gpx_only=True,
            )

        date_msgs = [r for r in caplog.records if "pushing workout_date=" in r.message]
        assert len(date_msgs) == 1
        assert "workout_date='2024-01-15 08:00'" in date_msgs[0].message
