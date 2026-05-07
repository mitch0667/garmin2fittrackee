import json
import logging
from typing import Any

import httpx

from garmin2fittrackee import FitTrackeeError
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

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class FitTrackeeClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token: str | None = None
        self._http = httpx.Client(timeout=30.0)

    def _authenticate(self) -> str:
        return self._authenticate_jwt()

    def _authenticate_jwt(self) -> str:
        data = {
            "email": self._username,
            "password": self._password,
        }
        resp = self._request(
            "POST",
            "/api/auth/login",
            json=data,
            auth_required=False,
        )
        body = resp.json()
        token: str = body.get("auth_token", "")
        if not token:
            raise FitTrackeeError(
                f"No auth_token in login response: {body}"
            )
        logger.info("Authenticated successfully via JWT login")
        self._token = token
        return token

    def _ensure_token(self) -> str:
        if self._token is None:
            self._authenticate()
        assert self._token is not None
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth_required: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if auth_required:
            headers["Authorization"] = f"Bearer {self._ensure_token()}"

        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._http.request(
                    method, url, headers=headers, **kwargs
                )
                if resp.status_code in RETRY_STATUS_CODES:
                    try:
                        body = resp.json()
                        if (
                            isinstance(body, dict)
                            and body.get("status") == "error"
                        ):
                            raise FitTrackeeError(
                                f"HTTP {resp.status_code}: "
                                f"{body.get('message', resp.text)}"
                            )
                    except (ValueError, KeyError):
                        pass
                    logger.warning(
                        "Retryable status %d on %s %s (attempt %d/%d)",
                        resp.status_code,
                        method,
                        path,
                        attempt,
                        MAX_RETRIES,
                    )
                    last_exc = FitTrackeeError(
                        f"HTTP {resp.status_code}: {resp.text}"
                    )
                    continue
                return resp
            except httpx.TransportError as exc:
                logger.warning(
                    "Transport error on %s %s (attempt %d/%d): %s",
                    method,
                    path,
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                last_exc = exc
                continue

        raise FitTrackeeError(
            f"Failed after {MAX_RETRIES} retries: {last_exc}"
        )

    def get_equipment_types(self) -> list[FitTrackeeEquipmentType]:
        resp = self._request("GET", "/api/equipment-types")
        body = resp.json()
        items = body.get("data", {}).get("equipment_types", [])
        return [FitTrackeeEquipmentType.model_validate(i) for i in items]

    def get_equipments(self) -> list[FitTrackeeEquipment]:
        resp = self._request("GET", "/api/equipments")
        body = resp.json()
        items = body.get("data", {}).get("equipments", [])
        return [FitTrackeeEquipment.model_validate(i) for i in items]

    def create_equipment(
        self, data: FitTrackeeEquipmentCreate
    ) -> FitTrackeeEquipment:
        resp = self._request(
            "POST",
            "/api/equipments",
            json=data.model_dump(exclude_none=True),
        )
        if resp.status_code != 201:
            raise FitTrackeeError(
                f"Failed to create equipment: HTTP {resp.status_code}: "
                f"{resp.text}"
            )
        body = resp.json()
        items = body.get("data", {}).get("equipments", [])
        if not items:
            raise FitTrackeeError("No equipment returned after creation")
        created = FitTrackeeEquipment.model_validate(items[0])

        if created.is_active != data.is_active:
            logger.warning(
                "FitTrackee ignored is_active=%s on creation, "
                "patching equipment '%s'",
                data.is_active,
                created.id,
            )
            update = FitTrackeeEquipmentUpdate(is_active=data.is_active)
            created = self.update_equipment(created.id, update)

        return created

    def update_equipment(
        self, equipment_id: str, data: FitTrackeeEquipmentUpdate
    ) -> FitTrackeeEquipment:
        resp = self._request(
            "PATCH",
            f"/api/equipments/{equipment_id}",
            json=data.model_dump(exclude_none=True),
        )
        if resp.status_code != 200:
            raise FitTrackeeError(
                f"Failed to update equipment {equipment_id}: "
                f"HTTP {resp.status_code}: {resp.text}"
            )
        body = resp.json()
        items = body.get("data", {}).get("equipments", [])
        if not items:
            raise FitTrackeeError(
                f"No equipment returned after update for {equipment_id}"
            )
        return FitTrackeeEquipment.model_validate(items[0])

    def get_sports(self) -> list[FitTrackeeSport]:
        resp = self._request("GET", "/api/sports")
        body = resp.json()
        items = body.get("data", {}).get("sports", [])
        return [FitTrackeeSport.model_validate(i) for i in items]

    def _get_workouts_raw(
        self, page: int = 1, per_page: int = 100
    ) -> tuple[list[FitTrackeeWorkout], bool]:
        resp = self._request(
            "GET",
            "/api/workouts",
            params={"page": page, "per_page": per_page, "order": "asc"},
        )
        body = resp.json()
        items = body.get("data", {}).get("workouts", [])
        workouts = [FitTrackeeWorkout.model_validate(i) for i in items]
        pagination = body.get("pagination", {})
        has_next = pagination.get("has_next", False)
        return workouts, has_next

    def get_workouts(
        self, page: int = 1, per_page: int = 100
    ) -> list[FitTrackeeWorkout]:
        workouts, _ = self._get_workouts_raw(page, per_page)
        return workouts

    def get_all_workouts(self) -> list[FitTrackeeWorkout]:
        all_workouts: list[FitTrackeeWorkout] = []
        page = 1
        while True:
            batch, has_next = self._get_workouts_raw(page=page)
            all_workouts.extend(batch)
            if not has_next:
                break
            page += 1
        return all_workouts

    def create_workout_no_gpx(
        self, data: FitTrackeeWorkoutCreateNoGpx
    ) -> FitTrackeeWorkout:
        resp = self._request(
            "POST",
            "/api/workouts/no_gpx",
            json=data.model_dump(exclude_none=True),
        )
        if resp.status_code != 201:
            raise FitTrackeeError(
                f"Failed to create workout: HTTP {resp.status_code}: "
                f"{resp.text}"
            )
        body = resp.json()
        items = body.get("data", {}).get("workouts", [])
        if not items:
            raise FitTrackeeError("No workout returned after creation")
        return FitTrackeeWorkout.model_validate(items[0])

    def create_workout_with_file(
        self, data: FitTrackeeWorkoutCreateNoGpx, file_path: str
    ) -> FitTrackeeWorkout:
        import os

        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            files = {"file": (filename, f)}
            file_data: dict[str, Any] = {
                "sport_id": data.sport_id,
            }
            if data.title is not None:
                file_data["title"] = data.title
            if data.notes is not None:
                file_data["notes"] = data.notes
            if data.description is not None:
                file_data["description"] = data.description
            if data.equipment_ids is not None:
                file_data["equipment_ids"] = data.equipment_ids
            data_str = json.dumps(file_data)
            form_data = {"data": data_str}

            resp = self._request(
                "POST",
                "/api/workouts",
                files=files,
                data=form_data,
            )

        if resp.status_code not in (200, 201):
            raise FitTrackeeError(
                f"Failed to create workout with file: HTTP {resp.status_code}: "
                f"{resp.text}"
            )

        if resp.status_code == 200:
            body = resp.json()
            task_id = body.get("data", {}).get("task_id")
            logger.info("Workout upload in progress, task_id=%s", task_id)
            return FitTrackeeWorkout(
                id="pending",
                sport_id=data.sport_id,
                title=data.title,
                workout_date=data.workout_date,
                duration="0:00:00",
            )

        body = resp.json()
        items = body.get("data", {}).get("workouts", [])
        if not items:
            raise FitTrackeeError("No workout returned after file upload")
        return FitTrackeeWorkout.model_validate(items[0])

    def update_workout(
        self, workout_id: str, data: FitTrackeeWorkoutUpdate
    ) -> FitTrackeeWorkout:
        resp = self._request(
            "PATCH",
            f"/api/workouts/{workout_id}",
            json=data.model_dump(exclude_none=True),
        )
        if resp.status_code != 200:
            raise FitTrackeeError(
                f"Failed to update workout {workout_id}: "
                f"HTTP {resp.status_code}: {resp.text}"
            )
        body = resp.json()
        items = body.get("data", {}).get("workouts", [])
        if not items:
            raise FitTrackeeError(
                f"No workout returned after update for {workout_id}"
            )
        return FitTrackeeWorkout.model_validate(items[0])

    def close(self) -> None:
        self._http.close()
