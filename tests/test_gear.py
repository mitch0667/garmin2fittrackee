import json
from pathlib import Path

import pytest

from garmin2fittrackee.garmin.gear import (
    GarminGear,
    find_gear_files,
    parse_all_gear_activity_mappings,
    parse_gear_activity_mapping,
    parse_gear_file,
)

SAMPLE_GEAR_DTO: dict[str, object] = {
    "gearPk": 12345,
    "uuid": "test-uuid",
    "userProfilePk": 1,
    "gearTypeName": "Shoes",
    "gearStatusName": "active",
    "customMakeModel": "Test Running Shoes",
    "dateBegin": "2020-01-01",
    "dateEnd": None,
    "maximumMeters": 500000.0,
    "notified": False,
    "gearVersion": 0,
    "createDate": "2020-01-01",
    "updateDate": "2020-01-01",
}


@pytest.fixture
def gear_json_list(tmp_path: Path) -> Path:
    data = [{"gearDTOS": [SAMPLE_GEAR_DTO]}]
    path = tmp_path / "test_gear.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def gear_json_direct(tmp_path: Path) -> Path:
    path = tmp_path / "test_gear.json"
    path.write_text(json.dumps([SAMPLE_GEAR_DTO]), encoding="utf-8")
    return path


class TestGarminGear:
    def test_label_from_custom_make_model(self) -> None:
        gear = GarminGear.model_validate(SAMPLE_GEAR_DTO)
        assert gear.label == "Test Running Shoes"

    def test_label_from_display_name(self) -> None:
        dto = {**SAMPLE_GEAR_DTO, "displayName": "My Shoes"}
        gear = GarminGear.model_validate(dto)
        assert gear.label == "My Shoes"

    def test_label_truncated_at_50_chars(self) -> None:
        long_name = "A" * 60
        dto = {**SAMPLE_GEAR_DTO, "customMakeModel": long_name}
        gear = GarminGear.model_validate(dto)
        assert len(gear.label) == 50
        assert gear.label.endswith("...")

    def test_is_active_true(self) -> None:
        gear = GarminGear.model_validate(SAMPLE_GEAR_DTO)
        assert gear.is_active is True

    def test_is_active_false_when_retired(self) -> None:
        dto = {**SAMPLE_GEAR_DTO, "gearStatusName": "retired"}
        gear = GarminGear.model_validate(dto)
        assert gear.is_active is False

    def test_date_end_none(self) -> None:
        gear = GarminGear.model_validate(SAMPLE_GEAR_DTO)
        assert gear.date_end is None

    def test_date_end_set(self) -> None:
        dto = {**SAMPLE_GEAR_DTO, "dateEnd": "2023-10-24"}
        gear = GarminGear.model_validate(dto)
        assert gear.date_end == "2023-10-24"


class TestParseGearFile:
    def test_parse_gear_dto_list(self, gear_json_list: Path) -> None:
        gears = parse_gear_file(gear_json_list)
        assert len(gears) == 1
        assert gears[0].gear_pk == 12345
        assert gears[0].gear_type_name == "Shoes"

    def test_parse_direct_list(self, gear_json_direct: Path) -> None:
        gears = parse_gear_file(gear_json_direct)
        assert len(gears) == 1

    def test_parse_multiple_items(self, tmp_path: Path) -> None:
        dto2 = {**SAMPLE_GEAR_DTO, "gearPk": 99999, "gearTypeName": "Bike"}
        data = [{"gearDTOS": [SAMPLE_GEAR_DTO, dto2]}]
        path = tmp_path / "multi_gear.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        gears = parse_gear_file(path)
        assert len(gears) == 2

    def test_parse_missing_file(self) -> None:
        from garmin2fittrackee import GearError

        with pytest.raises(GearError, match="Gear file not found"):
            parse_gear_file(Path("/nonexistent/gear.json"))

    def test_parse_invalid_json(self, tmp_path: Path) -> None:
        from garmin2fittrackee import GearError

        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(GearError, match="Invalid gear JSON"):
            parse_gear_file(path)

    def test_parse_unexpected_structure(self, tmp_path: Path) -> None:
        from garmin2fittrackee import GearError

        path = tmp_path / "weird.json"
        path.write_text(json.dumps({"unexpected": "data"}), encoding="utf-8")
        with pytest.raises(GearError, match="Unexpected gear data"):
            parse_gear_file(path)

    def test_parse_skips_invalid_entries(self, tmp_path: Path) -> None:
        data = [{"gearDTOS": [{"bad": "entry"}, SAMPLE_GEAR_DTO]}]
        path = tmp_path / "partial.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        gears = parse_gear_file(path)
        assert len(gears) == 1


class TestFindGearFiles:
    def test_finds_gear_files(self, tmp_path: Path) -> None:
        (tmp_path / "DI_CONNECT").mkdir()
        di = tmp_path / "DI_CONNECT"
        di.joinpath("user_gear.json").write_text("[]")
        di.joinpath("other_file.json").write_text("{}")
        files = find_gear_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "user_gear.json"

    def test_finds_no_gear_files(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text("{}")
        files = find_gear_files(tmp_path)
        assert files == []

    def test_finds_nested_gear_files(self, tmp_path: Path) -> None:
        nested = tmp_path / "DI_CONNECT" / "DI-Connect-Fitness"
        nested.mkdir(parents=True)
        nested.joinpath("baehl_gear.json").write_text("[]")
        files = find_gear_files(tmp_path)
        assert len(files) == 1


class TestParseGearActivityMapping:
    def test_builds_reverse_index(self, tmp_path: Path) -> None:
        data = [{
            "gearDTOS": [],
            "gearActivityDTOs": {
                "100": [
                    {"gearPk": 100, "activityId": 1001},
                    {"gearPk": 100, "activityId": 1002},
                ],
                "200": [
                    {"gearPk": 200, "activityId": 1001},
                ],
            },
        }]
        path = tmp_path / "test_gear.json"
        path.write_text(json.dumps(data))
        result = parse_gear_activity_mapping(path)
        assert result[1001] == [100, 200]
        assert result[1002] == [100]
        assert 1003 not in result

    def test_empty_mapping(self, tmp_path: Path) -> None:
        data = [{"gearDTOS": [], "gearActivityDTOs": {}}]
        path = tmp_path / "test_gear.json"
        path.write_text(json.dumps(data))
        result = parse_gear_activity_mapping(path)
        assert result == {}

    def test_no_gear_activity_dtos_key(self, tmp_path: Path) -> None:
        data = [{"gearDTOS": [SAMPLE_GEAR_DTO]}]
        path = tmp_path / "test_gear.json"
        path.write_text(json.dumps(data))
        result = parse_gear_activity_mapping(path)
        assert result == {}

    def test_missing_file_raises(self) -> None:
        from garmin2fittrackee import GearError

        with pytest.raises(GearError, match="Gear file not found"):
            parse_gear_activity_mapping(Path("/nonexistent/gear.json"))

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        from garmin2fittrackee import GearError

        path = tmp_path / "bad.json"
        path.write_text("not json")
        with pytest.raises(GearError, match="Invalid gear JSON"):
            parse_gear_activity_mapping(path)

    def test_dict_top_level(self, tmp_path: Path) -> None:
        data = {
            "gearDTOS": [],
            "gearActivityDTOs": {
                "300": [{"gearPk": 300, "activityId": 5000}],
            },
        }
        path = tmp_path / "test_gear.json"
        path.write_text(json.dumps(data))
        result = parse_gear_activity_mapping(path)
        assert result == {5000: [300]}

    def test_skips_invalid_entries(self, tmp_path: Path) -> None:
        data = [{
            "gearDTOS": [],
            "gearActivityDTOs": {
                "100": [
                    {"gearPk": 100, "activityId": 1001},
                    {"invalid": True},
                ],
            },
        }]
        path = tmp_path / "test_gear.json"
        path.write_text(json.dumps(data))
        result = parse_gear_activity_mapping(path)
        assert result == {1001: [100]}


class TestParseAllGearActivityMappings:
    def test_combines_multiple_files(self, tmp_path: Path) -> None:
        d1 = [{"gearDTOS": [], "gearActivityDTOs": {
            "100": [{"gearPk": 100, "activityId": 1001}],
        }}]
        d2 = [{"gearDTOS": [], "gearActivityDTOs": {
            "200": [{"gearPk": 200, "activityId": 1002}],
        }}]
        (tmp_path / "a_gear.json").write_text(json.dumps(d1))
        (tmp_path / "b_gear.json").write_text(json.dumps(d2))

        result = parse_all_gear_activity_mappings(tmp_path)
        assert result[1001] == [100]
        assert result[1002] == [200]

    def test_no_files_returns_empty(self, tmp_path: Path) -> None:
        result = parse_all_gear_activity_mappings(tmp_path)
        assert result == {}
