from garmin2fittrackee.garmin.garmin_products import (
    GARMIN_DEVICES,
    resolve_product_id,
)


class TestResolveProductId:
    def test_exact_match_forerunner_945(self) -> None:
        assert resolve_product_id("Forerunner 945") == 3113

    def test_exact_match_case_insensitive(self) -> None:
        assert resolve_product_id("forerunner 945") == 3113

    def test_exact_match_with_garmin_prefix(self) -> None:
        assert resolve_product_id("Garmin Forerunner 945") == 3113

    def test_exact_match_edge_530(self) -> None:
        assert resolve_product_id("Edge 530") == 3121

    def test_fuzzy_match_fenix_6(self) -> None:
        result = resolve_product_id("Fenix 6")
        assert result is not None
        name = GARMIN_DEVICES[result].lower()
        assert "fenix 6" in name

    def test_fuzzy_match_fenix_7(self) -> None:
        result = resolve_product_id("Fenix 7")
        assert result is not None
        name = GARMIN_DEVICES[result].lower()
        assert "fenix 7" in name or "fenix" == name

    def test_fuzzy_match_strips_solar_suffix(self) -> None:
        result = resolve_product_id("Fenix 6 Solar")
        assert result is not None
        assert "Fenix 6" in GARMIN_DEVICES[result]

    def test_fuzzy_match_strips_pro_solar(self) -> None:
        result = resolve_product_id("Fenix 7 Pro Solar")
        assert result is not None
        assert result == 4375

    def test_unknown_device_returns_none(self) -> None:
        assert resolve_product_id("Unknown Device XYZ") is None

    def test_empty_string_returns_none(self) -> None:
        assert resolve_product_id("") is None

    def test_vivoactive_4(self) -> None:
        assert resolve_product_id("Vivoactive 4") == 3224

    def test_instinct(self) -> None:
        result = resolve_product_id("Instinct")
        assert result is not None
        assert GARMIN_DEVICES[result] == "Instinct"

    def test_forerunner_265(self) -> None:
        assert resolve_product_id("Forerunner 265") == 4257


class TestGarminDevicesMapping:
    def test_mapping_not_empty(self) -> None:
        assert len(GARMIN_DEVICES) > 100

    def test_fenix_7s_solar_exists(self) -> None:
        assert 3906 in GARMIN_DEVICES
        assert GARMIN_DEVICES[3906] == "Fenix 7S Solar"

    def test_fenix_7_pro_solar_exists(self) -> None:
        assert 4375 in GARMIN_DEVICES
        assert GARMIN_DEVICES[4375] == "Fenix 7 Pro Solar"

    def test_product_ids_are_positive(self) -> None:
        for pid in GARMIN_DEVICES:
            assert pid > 0

    def test_names_are_non_empty(self) -> None:
        for pid, name in GARMIN_DEVICES.items():
            assert len(name) > 0
