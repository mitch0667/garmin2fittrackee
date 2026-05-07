import httpx
import pytest
import respx

from garmin2fittrackee import FitTrackeeError
from garmin2fittrackee.fittrackee.client import FitTrackeeClient
from garmin2fittrackee.fittrackee.models import (
    FitTrackeeEquipmentCreate,
    FitTrackeeEquipmentUpdate,
    FitTrackeeWorkoutCreateNoGpx,
    FitTrackeeWorkoutUpdate,
)

BASE_URL = "https://fittrackee.example.com"

JWT_AUTH_RESPONSE = {
    "auth_token": "jwt-token-456",
    "message": "successfully logged in",
    "status": "success",
}

EQUIPMENT_TYPE_RESPONSE = {
    "data": {
        "equipment_types": [
            {"id": 1, "label": "Shoe", "is_active": True},
            {"id": 2, "label": "Bike", "is_active": True},
        ]
    },
    "status": "success",
}

EQUIPMENT_LIST_RESPONSE = {
    "data": {
        "equipments": [
            {
                "id": "abc123",
                "label": "Existing Shoes",
                "is_active": True,
                "description": None,
                "creation_date": "Tue, 21 Mar 2023 06:08:06 GMT",
                "equipment_type": {"id": 1, "label": "Shoe", "is_active": True},
                "default_for_sport_ids": [],
                "total_distance": 0.0,
                "total_duration_in_hours": 0,
                "workouts_count": 0,
            }
        ]
    },
    "status": "success",
}


def _client() -> FitTrackeeClient:
    return FitTrackeeClient(
        base_url=BASE_URL,
        username="testuser",
        password="testpass",
    )


class TestAuth:
    @respx.mock
    def test_authenticate_jwt_success(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        c = _client()
        c._authenticate()
        assert c._token == "jwt-token-456"
        c.close()

    @respx.mock
    def test_authenticate_jwt_no_token_in_response(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json={})
        )
        c = _client()
        with pytest.raises(FitTrackeeError, match="No auth_token"):
            c._authenticate()
        c.close()


class TestGetEquipmentTypes:
    @respx.mock
    def test_get_equipment_types(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.get(f"{BASE_URL}/api/equipment-types").mock(
            return_value=httpx.Response(200, json=EQUIPMENT_TYPE_RESPONSE)
        )
        c = _client()
        types = c.get_equipment_types()
        assert len(types) == 2
        assert types[0].label == "Shoe"
        assert types[1].id == 2
        c.close()


class TestGetEquipments:
    @respx.mock
    def test_get_equipments(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.get(f"{BASE_URL}/api/equipments").mock(
            return_value=httpx.Response(200, json=EQUIPMENT_LIST_RESPONSE)
        )
        c = _client()
        eqs = c.get_equipments()
        assert len(eqs) == 1
        assert eqs[0].label == "Existing Shoes"
        c.close()


class TestCreateEquipment:
    @respx.mock
    def test_create_success(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        create_resp = {
            "data": {
                "equipments": [
                    {
                        "id": "new123",
                        "label": "New Shoes",
                        "is_active": True,
                        "description": None,
                        "creation_date": "Tue, 21 Mar 2023 06:08:06 GMT",
                        "equipment_type": {
                            "id": 1,
                            "label": "Shoe",
                            "is_active": True,
                        },
                        "default_for_sport_ids": [],
                        "total_distance": 0.0,
                        "total_duration_in_hours": 0,
                        "workouts_count": 0,
                    }
                ]
            },
            "status": "created",
        }
        respx.post(f"{BASE_URL}/api/equipments").mock(
            return_value=httpx.Response(201, json=create_resp)
        )
        c = _client()
        data = FitTrackeeEquipmentCreate(
            label="New Shoes", equipment_type_id=1
        )
        result = c.create_equipment(data)
        assert result.id == "new123"
        assert result.label == "New Shoes"
        c.close()

    @respx.mock
    def test_create_inactive_patches_when_api_ignores(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        create_resp = {
            "data": {
                "equipments": [
                    {
                        "id": "new456",
                        "label": "Retired Shoes",
                        "is_active": True,
                        "description": None,
                        "creation_date": "Tue, 21 Mar 2023 06:08:06 GMT",
                        "equipment_type": {
                            "id": 1,
                            "label": "Shoe",
                            "is_active": True,
                        },
                        "default_for_sport_ids": [],
                        "total_distance": 0.0,
                        "total_duration_in_hours": 0,
                        "workouts_count": 0,
                    }
                ]
            },
            "status": "created",
        }
        update_resp = {
            "data": {
                "equipments": [
                    {
                        "id": "new456",
                        "label": "Retired Shoes",
                        "is_active": False,
                        "description": None,
                        "creation_date": "Tue, 21 Mar 2023 06:08:06 GMT",
                        "equipment_type": {
                            "id": 1,
                            "label": "Shoe",
                            "is_active": True,
                        },
                        "default_for_sport_ids": [],
                        "total_distance": 0.0,
                        "total_duration_in_hours": 0,
                        "workouts_count": 0,
                    }
                ]
            },
            "status": "success",
        }
        respx.post(f"{BASE_URL}/api/equipments").mock(
            return_value=httpx.Response(201, json=create_resp)
        )
        respx.patch(f"{BASE_URL}/api/equipments/new456").mock(
            return_value=httpx.Response(200, json=update_resp)
        )
        c = _client()
        data = FitTrackeeEquipmentCreate(
            label="Retired Shoes", equipment_type_id=1, is_active=False
        )
        result = c.create_equipment(data)
        assert result.id == "new456"
        assert result.is_active is False
        c.close()

    @respx.mock
    def test_create_failure(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.post(f"{BASE_URL}/api/equipments").mock(
            return_value=httpx.Response(
                400,
                json={
                    "message": "equipment already exists with the same label",
                    "status": "error",
                },
            )
        )
        c = _client()
        data = FitTrackeeEquipmentCreate(
            label="New Shoes", equipment_type_id=1
        )
        with pytest.raises(FitTrackeeError, match="Failed to create"):
            c.create_equipment(data)
        c.close()


class TestUpdateEquipment:
    @respx.mock
    def test_update_success(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        update_resp = {
            "data": {
                "equipments": [
                    {
                        "id": "abc123",
                        "label": "Updated Shoes",
                        "is_active": False,
                        "description": None,
                        "creation_date": "Tue, 21 Mar 2023 06:08:06 GMT",
                        "equipment_type": {
                            "id": 1,
                            "label": "Shoe",
                            "is_active": True,
                        },
                        "default_for_sport_ids": [],
                        "total_distance": 0.0,
                        "total_duration_in_hours": 0,
                        "workouts_count": 0,
                    }
                ]
            },
            "status": "success",
        }
        respx.patch(f"{BASE_URL}/api/equipments/abc123").mock(
            return_value=httpx.Response(200, json=update_resp)
        )
        c = _client()
        data = FitTrackeeEquipmentUpdate(is_active=False)
        result = c.update_equipment("abc123", data)
        assert result.is_active is False
        c.close()

    @respx.mock
    def test_update_not_found(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.patch(f"{BASE_URL}/api/equipments/missing").mock(
            return_value=httpx.Response(
                404, json={"data": {"equipments": []}, "status": "not found"}
            )
        )
        c = _client()
        with pytest.raises(FitTrackeeError, match="Failed to update"):
            c.update_equipment("missing", FitTrackeeEquipmentUpdate())
        c.close()


class TestRetry:
    @respx.mock
    def test_retries_on_429(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        route = respx.get(f"{BASE_URL}/api/equipment-types")
        route.side_effect = [
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json=EQUIPMENT_TYPE_RESPONSE),
        ]
        c = _client()
        types = c.get_equipment_types()
        assert len(types) == 2
        c.close()


SPORTS_RESPONSE = {
    "data": {
        "sports": [
            {
                "id": 1,
                "label": "Cycling (Sport)",
                "is_active": True,
                "is_active_for_user": True,
            },
            {
                "id": 5,
                "label": "Running",
                "is_active": True,
                "is_active_for_user": True,
            },
        ]
    },
    "status": "success",
}

WORKOUTS_RESPONSE = {
    "data": {
        "workouts": [
            {
                "id": "wk001",
                "sport_id": 5,
                "title": "Morning Run",
                "workout_date": "2024-01-15 08:00:00",
                "duration": "0:30:00",
                "distance": 5.0,
                "with_file": False,
            }
        ]
    },
    "pagination": {"has_next": False, "page": 1, "pages": 1, "total": 1},
    "status": "success",
}


class TestGetSports:
    @respx.mock
    def test_get_sports(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.get(f"{BASE_URL}/api/sports").mock(
            return_value=httpx.Response(200, json=SPORTS_RESPONSE)
        )
        c = _client()
        sports = c.get_sports()
        assert len(sports) == 2
        assert sports[0].label == "Cycling (Sport)"
        assert sports[1].id == 5
        c.close()


class TestGetWorkouts:
    @respx.mock
    def test_get_workouts(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.get(f"{BASE_URL}/api/workouts").mock(
            return_value=httpx.Response(200, json=WORKOUTS_RESPONSE)
        )
        c = _client()
        workouts = c.get_workouts()
        assert len(workouts) == 1
        assert workouts[0].id == "wk001"
        assert workouts[0].sport_id == 5
        c.close()

    @respx.mock
    def test_get_all_workouts_pagination(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        page1 = {
            "data": {
                "workouts": [
                    {
                        "id": "wk001",
                        "sport_id": 5,
                        "workout_date": "2024-01-01 08:00:00",
                        "duration": "0:30:00",
                    }
                ]
            },
            "pagination": {"has_next": True},
            "status": "success",
        }
        page2 = {
            "data": {
                "workouts": [
                    {
                        "id": "wk002",
                        "sport_id": 1,
                        "workout_date": "2024-01-02 08:00:00",
                        "duration": "1:00:00",
                    }
                ]
            },
            "pagination": {"has_next": False},
            "status": "success",
        }
        route = respx.get(f"{BASE_URL}/api/workouts")
        route.side_effect = [
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
        c = _client()
        workouts = c.get_all_workouts()
        assert len(workouts) == 2
        c.close()


class TestCreateWorkoutNoGpx:
    @respx.mock
    def test_create_success(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        create_resp = {
            "data": {
                "workouts": [
                    {
                        "id": "wknew",
                        "sport_id": 5,
                        "title": "Test Run",
                        "workout_date": "2024-01-15 08:00:00",
                        "duration": "0:30:00",
                        "distance": 5.0,
                        "with_file": False,
                    }
                ]
            },
            "status": "created",
        }
        respx.post(f"{BASE_URL}/api/workouts/no_gpx").mock(
            return_value=httpx.Response(201, json=create_resp)
        )
        c = _client()
        data = FitTrackeeWorkoutCreateNoGpx(
            sport_id=5,
            duration=1800,
            distance=5.0,
            workout_date="2024-01-15 08:00:00",
            title="Test Run",
        )
        result = c.create_workout_no_gpx(data)
        assert result.id == "wknew"
        c.close()

    @respx.mock
    def test_create_failure(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.post(f"{BASE_URL}/api/workouts/no_gpx").mock(
            return_value=httpx.Response(
                400, json={"message": "invalid payload", "status": "error"}
            )
        )
        c = _client()
        data = FitTrackeeWorkoutCreateNoGpx(
            sport_id=5,
            duration=1800,
            distance=5.0,
            workout_date="2024-01-15 08:00:00",
        )
        with pytest.raises(FitTrackeeError, match="Failed to create workout"):
            c.create_workout_no_gpx(data)
        c.close()


class TestUpdateWorkout:
    @respx.mock
    def test_update_success(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        update_resp = {
            "data": {
                "workouts": [
                    {
                        "id": "wk001",
                        "sport_id": 5,
                        "title": "Updated Run",
                        "workout_date": "2024-01-15 08:00:00",
                        "duration": "0:30:00",
                        "distance": 5.0,
                        "with_file": False,
                    }
                ]
            },
            "status": "success",
        }
        respx.patch(f"{BASE_URL}/api/workouts/wk001").mock(
            return_value=httpx.Response(200, json=update_resp)
        )
        c = _client()
        data = FitTrackeeWorkoutUpdate(title="Updated Run")
        result = c.update_workout("wk001", data)
        assert result.title == "Updated Run"
        c.close()

    @respx.mock
    def test_update_not_found(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        respx.patch(f"{BASE_URL}/api/workouts/missing").mock(
            return_value=httpx.Response(
                404, json={"message": "not found", "status": "not found"}
            )
        )
        c = _client()
        with pytest.raises(FitTrackeeError, match="Failed to update workout"):
            c.update_workout("missing", FitTrackeeWorkoutUpdate(title="X"))
        c.close()

    @respx.mock
    def test_update_with_equipment(self) -> None:
        respx.post(f"{BASE_URL}/api/auth/login").mock(
            return_value=httpx.Response(200, json=JWT_AUTH_RESPONSE)
        )
        update_resp = {
            "data": {
                "workouts": [
                    {
                        "id": "wk001",
                        "sport_id": 5,
                        "title": "Run",
                        "workout_date": "2024-01-15 08:00:00",
                        "duration": "0:30:00",
                        "distance": 5.0,
                        "with_file": False,
                    }
                ]
            },
            "status": "success",
        }
        respx.patch(f"{BASE_URL}/api/workouts/wk001").mock(
            return_value=httpx.Response(200, json=update_resp)
        )
        c = _client()
        data = FitTrackeeWorkoutUpdate(
            equipment_ids=["eq1", "eq2"]
        )
        result = c.update_workout("wk001", data)
        assert result.id == "wk001"
        c.close()
