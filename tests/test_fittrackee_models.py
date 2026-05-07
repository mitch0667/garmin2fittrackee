from garmin2fittrackee.fittrackee.models import (
    FitTrackeeEquipment,
    FitTrackeeEquipmentCreate,
    FitTrackeeEquipmentType,
    FitTrackeeEquipmentUpdate,
    FitTrackeeSport,
    FitTrackeeWorkout,
    FitTrackeeWorkoutCreateNoGpx,
)


class TestFitTrackeeEquipmentType:
    def test_valid_type(self) -> None:
        t = FitTrackeeEquipmentType(id=1, label="Shoe", is_active=True)
        assert t.id == 1
        assert t.label == "Shoe"

    def test_inactive_type(self) -> None:
        t = FitTrackeeEquipmentType(id=99, label="Old", is_active=False)
        assert t.is_active is False


class TestFitTrackeeEquipment:
    def test_valid_equipment(self) -> None:
        eq = FitTrackeeEquipment(
            id="abc123",
            label="My Shoes",
            is_active=True,
            equipment_type=FitTrackeeEquipmentType(
                id=1, label="Shoe", is_active=True
            ),
        )
        assert eq.label == "My Shoes"
        assert eq.equipment_type.id == 1
        assert eq.total_distance == 0.0
        assert eq.workouts_count == 0

    def test_with_optional_fields(self) -> None:
        eq = FitTrackeeEquipment(
            id="abc123",
            label="My Shoes",
            is_active=True,
            description="Test shoes",
            creation_date="Tue, 21 Mar 2023 06:08:06 GMT",
            equipment_type=FitTrackeeEquipmentType(
                id=1, label="Shoe", is_active=True
            ),
            default_for_sport_ids=[1, 2],
            total_distance=100.5,
            total_duration_in_hours=10,
            workouts_count=5,
        )
        assert eq.description == "Test shoes"
        assert eq.default_for_sport_ids == [1, 2]


class TestFitTrackeeEquipmentCreate:
    def test_minimal(self) -> None:
        c = FitTrackeeEquipmentCreate(
            label="New Shoes", equipment_type_id=1
        )
        assert c.is_active is True
        assert c.description is None
        assert c.default_for_sport_ids == []

    def test_full(self) -> None:
        c = FitTrackeeEquipmentCreate(
            label="New Shoes",
            equipment_type_id=1,
            description="Desc",
            is_active=False,
            default_for_sport_ids=[3],
        )
        assert c.is_active is False
        dumped = c.model_dump(exclude_none=True)
        assert "description" in dumped


class TestFitTrackeeEquipmentUpdate:
    def test_all_none(self) -> None:
        u = FitTrackeeEquipmentUpdate()
        dumped = u.model_dump(exclude_none=True)
        assert dumped == {}

    def test_partial_update(self) -> None:
        u = FitTrackeeEquipmentUpdate(is_active=False)
        dumped = u.model_dump(exclude_none=True)
        assert dumped == {"is_active": False}


class TestFitTrackeeSport:
    def test_valid_sport(self) -> None:
        s = FitTrackeeSport(id=5, label="Running", is_active=True)
        assert s.id == 5
        assert s.label == "Running"

    def test_inactive_sport(self) -> None:
        s = FitTrackeeSport(id=99, label="Archery", is_active=False)
        assert s.is_active is False


class TestFitTrackeeWorkout:
    def test_valid_workout(self) -> None:
        w = FitTrackeeWorkout(
            id="abc123",
            sport_id=5,
            title="Morning Run",
            workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
            distance=5.0,
        )
        assert w.sport_id == 5
        assert w.distance == 5.0
        assert w.with_file is False

    def test_with_optional_fields(self) -> None:
        w = FitTrackeeWorkout(
            id="abc123",
            sport_id=5,
            workout_date="2024-01-15 08:00:00",
            duration="0:30:00",
            moving="0:28:00",
            ascent=100.0,
            descent=80.0,
            ave_speed=10.0,
            max_speed=12.0,
            notes="Great run",
            with_file=True,
        )
        assert w.ascent == 100.0
        assert w.notes == "Great run"


class TestFitTrackeeWorkoutCreateNoGpx:
    def test_minimal(self) -> None:
        c = FitTrackeeWorkoutCreateNoGpx(
            sport_id=5,
            duration=1800,
            distance=5.0,
            workout_date="2024-01-15 08:00:00",
        )
        assert c.title is None
        assert c.ascent is None

    def test_full(self) -> None:
        c = FitTrackeeWorkoutCreateNoGpx(
            sport_id=5,
            duration=1800,
            distance=5.0,
            workout_date="2024-01-15 08:00:00",
            title="Morning Run",
            notes="Felt good",
            description="Test",
            ascent=100.0,
            descent=80.0,
        )
        dumped = c.model_dump(exclude_none=True)
        assert dumped["sport_id"] == 5
        assert dumped["ascent"] == 100.0
