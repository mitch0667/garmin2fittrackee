from pydantic import BaseModel


class FitTrackeeEquipmentType(BaseModel):
    id: int
    label: str
    is_active: bool


class FitTrackeeEquipment(BaseModel):
    id: str
    label: str
    is_active: bool
    description: str | None = None
    creation_date: str | None = None
    equipment_type: FitTrackeeEquipmentType
    default_for_sport_ids: list[int] = []
    total_distance: float = 0.0
    total_duration_in_hours: float = 0.0
    workouts_count: int = 0


class FitTrackeeEquipmentCreate(BaseModel):
    label: str
    equipment_type_id: int
    description: str | None = None
    is_active: bool = True
    default_for_sport_ids: list[int] = []


class FitTrackeeEquipmentUpdate(BaseModel):
    label: str | None = None
    equipment_type_id: int | None = None
    description: str | None = None
    is_active: bool | None = None
    default_for_sport_ids: list[int] | None = None


class FitTrackeeSport(BaseModel):
    id: int
    label: str
    is_active: bool = True
    is_active_for_user: bool = True


class FitTrackeeWorkout(BaseModel):
    id: str
    sport_id: int
    title: str | None = None
    workout_date: str
    duration: str
    moving: str | None = None
    distance: float = 0.0
    ascent: float | None = None
    descent: float | None = None
    ave_speed: float | None = None
    max_speed: float | None = None
    notes: str | None = None
    description: str | None = None
    equipment_ids: list[str] | None = None
    with_file: bool = False


class FitTrackeeWorkoutCreateNoGpx(BaseModel):
    sport_id: int
    duration: int
    distance: float
    workout_date: str
    title: str | None = None
    notes: str | None = None
    description: str | None = None
    ascent: float | None = None
    descent: float | None = None
    equipment_ids: list[str] | None = None


class FitTrackeeWorkoutUpdate(BaseModel):
    sport_id: int | None = None
    title: str | None = None
    notes: str | None = None
    description: str | None = None
    distance: float | None = None
    duration: int | None = None
    workout_date: str | None = None
    ascent: float | None = None
    descent: float | None = None
    equipment_ids: list[str] | None = None
