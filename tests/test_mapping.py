from pathlib import Path

import pytest

from garmin2fittrackee import MappingError
from garmin2fittrackee.fittrackee.models import FitTrackeeEquipmentType, FitTrackeeSport
from garmin2fittrackee.mapping import (
    DEFAULT_ACTIVITY_MAPPING_FILE,
    DEFAULT_EQUIPMENT_MAPPING_FILE,
    load_activity_mapping,
    load_mapping,
    resolve_equipment_type_id,
    resolve_sport_id,
)


class TestLoadMapping:
    def test_load_default_mapping(self) -> None:
        mapping = load_mapping()
        assert "Bike" in mapping
        assert mapping["Bike"] == "Bike"
        assert "Shoes" in mapping
        assert mapping["Shoes"] == "Shoes"

    def test_default_mapping_file_exists(self) -> None:
        assert DEFAULT_EQUIPMENT_MAPPING_FILE.exists()

    def test_load_custom_mapping(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "custom.toml"
        toml_file.write_text(
            '[gear_type_mapping]\n"Bike" = "Bike"\n"Shoes" = "Shoe"\n'
        )
        mapping = load_mapping(toml_file)
        assert "Bike" in mapping

    def test_load_missing_file(self) -> None:
        with pytest.raises(MappingError, match="Mapping file not found"):
            load_mapping(Path("/nonexistent.toml"))

    def test_load_empty_mapping_section(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "empty.toml"
        toml_file.write_text("[other_section]\nkey = 'value'\n")
        with pytest.raises(MappingError, match="No \\[gear_type_mapping\\]"):
            load_mapping(toml_file)

    def test_load_invalid_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "bad.toml"
        toml_file.write_text("not valid toml [[[")
        with pytest.raises(MappingError, match="Failed to parse"):
            load_mapping(toml_file)


class TestResolveEquipmentTypeId:
    FT_TYPES = [
        FitTrackeeEquipmentType(id=1, label="Shoe", is_active=True),
        FitTrackeeEquipmentType(id=2, label="Bike", is_active=True),
        FitTrackeeEquipmentType(id=3, label="Skis", is_active=False),
    ]

    def test_resolve_known_type(self) -> None:
        mapping = {"Shoes": "Shoe", "Bike": "Bike"}
        result = resolve_equipment_type_id("Shoes", mapping, self.FT_TYPES)
        assert result == 1

    def test_resolve_bike(self) -> None:
        mapping = {"Shoes": "Shoe", "Bike": "Bike"}
        result = resolve_equipment_type_id("Bike", mapping, self.FT_TYPES)
        assert result == 2

    def test_unmapped_type_returns_none(self) -> None:
        mapping = {"Shoes": "Shoe"}
        result = resolve_equipment_type_id("Other", mapping, self.FT_TYPES)
        assert result is None

    def test_inactive_type_returns_none(self) -> None:
        mapping = {"Skis": "Skis"}
        result = resolve_equipment_type_id("Skis", mapping, self.FT_TYPES)
        assert result is None

    def test_case_insensitive_matching(self) -> None:
        mapping = {"Shoes": "shoe"}
        result = resolve_equipment_type_id("Shoes", mapping, self.FT_TYPES)
        assert result == 1

    def test_mapped_but_not_in_ft_types(self) -> None:
        mapping = {"Other": "Kayak_Boat"}
        result = resolve_equipment_type_id(
            "Other", mapping, self.FT_TYPES
        )
        assert result is None


class TestLoadActivityMapping:
    def test_load_default_mapping(self) -> None:
        mapping = load_activity_mapping()
        assert "running" in mapping
        assert mapping["running"] == "Running"
        assert "cycling" in mapping
        assert "hiking" in mapping

    def test_default_file_exists(self) -> None:
        assert DEFAULT_ACTIVITY_MAPPING_FILE.exists()

    def test_load_custom_mapping(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "custom.toml"
        toml_file.write_text(
            '[activity_type_mapping]\n"running" = "Running"\n'
        )
        mapping = load_activity_mapping(toml_file)
        assert "running" in mapping

    def test_missing_file(self) -> None:
        with pytest.raises(MappingError, match="Activity mapping file not found"):
            load_activity_mapping(Path("/nonexistent.toml"))

    def test_empty_section(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "empty.toml"
        toml_file.write_text("[other]\nkey = 'value'\n")
        with pytest.raises(MappingError, match="No \\[activity_type_mapping\\]"):
            load_activity_mapping(toml_file)


class TestResolveSportId:
    SPORTS = [
        FitTrackeeSport(id=1, label="Cycling (Sport)", is_active=True),
        FitTrackeeSport(id=5, label="Running", is_active=True),
        FitTrackeeSport(id=3, label="Hiking", is_active=True),
        FitTrackeeSport(id=4, label="Mountain Biking", is_active=False),
    ]

    def test_resolve_running(self) -> None:
        mapping = {"running": "Running"}
        result = resolve_sport_id("running", mapping, self.SPORTS)
        assert result == 5

    def test_resolve_cycling(self) -> None:
        mapping = {"cycling": "Cycling (Sport)"}
        result = resolve_sport_id("cycling", mapping, self.SPORTS)
        assert result == 1

    def test_unmapped_returns_none(self) -> None:
        mapping = {"running": "Running"}
        result = resolve_sport_id("unknown", mapping, self.SPORTS)
        assert result is None

    def test_other_mapping_returns_none(self) -> None:
        mapping = {"yoga": "Other"}
        result = resolve_sport_id("yoga", mapping, self.SPORTS)
        assert result is None

    def test_inactive_sport_returns_none(self) -> None:
        mapping = {"mountain_biking": "Mountain Biking"}
        result = resolve_sport_id(
            "mountain_biking", mapping, self.SPORTS
        )
        assert result is None

    def test_case_insensitive(self) -> None:
        mapping = {"running": "running"}
        result = resolve_sport_id("running", mapping, self.SPORTS)
        assert result == 5
