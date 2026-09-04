import pytest

from app.report_settings import ReportSettingsError, validate


def test_validate_empty_patch_ok():
    assert validate({}) == {}


def test_validate_valid_default_columns():
    patch = {"default_columns": ["begin", "energy", "cost"]}
    assert validate(patch) == patch


def test_validate_empty_default_columns_raises():
    with pytest.raises(ReportSettingsError):
        validate({"default_columns": []})


def test_validate_default_columns_not_a_list_raises():
    with pytest.raises(ReportSettingsError):
        validate({"default_columns": "begin"})


def test_validate_unknown_column_raises():
    with pytest.raises(ReportSettingsError):
        validate({"default_columns": ["not_a_real_column"]})


def test_validate_valid_cost_basis():
    assert validate({"cost_basis": "openwb"}) == {"cost_basis": "openwb"}
    assert validate({"cost_basis": "corrected"}) == {"cost_basis": "corrected"}


def test_validate_unknown_cost_basis_raises():
    with pytest.raises(ReportSettingsError):
        validate({"cost_basis": "bogus"})


def test_validate_show_signature_line_bool_ok():
    assert validate({"show_signature_line": True}) == {"show_signature_line": True}
    assert validate({"show_signature_line": False}) == {"show_signature_line": False}


def test_validate_show_signature_line_non_bool_raises():
    with pytest.raises(ReportSettingsError):
        validate({"show_signature_line": "yes"})


def test_validate_multiple_fields_at_once():
    patch = {"cost_basis": "openwb", "show_signature_line": True}
    assert validate(patch) == patch


def test_validate_valid_orientation():
    assert validate({"orientation": "portrait"}) == {"orientation": "portrait"}
    assert validate({"orientation": "landscape"}) == {"orientation": "landscape"}


def test_validate_unknown_orientation_raises():
    with pytest.raises(ReportSettingsError):
        validate({"orientation": "sideways"})


def test_validate_valid_pv_bat_price():
    patch = {"pv_price_per_kwh": 0.12, "bat_price_per_kwh": 0.20}
    assert validate(patch) == patch
    assert validate({"pv_price_per_kwh": 0}) == {"pv_price_per_kwh": 0}


def test_validate_negative_pv_price_raises():
    with pytest.raises(ReportSettingsError):
        validate({"pv_price_per_kwh": -0.01})


def test_validate_negative_bat_price_raises():
    with pytest.raises(ReportSettingsError):
        validate({"bat_price_per_kwh": -0.01})


def test_validate_non_numeric_pv_price_raises():
    with pytest.raises(ReportSettingsError):
        validate({"pv_price_per_kwh": "cheap"})


def test_validate_bool_pv_price_raises():
    with pytest.raises(ReportSettingsError):
        validate({"pv_price_per_kwh": True})
