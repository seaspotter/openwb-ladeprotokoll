import pytest

from app.app_settings import AppSettingsError, validate


def test_validate_empty_patch_ok():
    assert validate({}) == {}


def test_validate_auto_fetch_enabled_bool_ok():
    assert validate({"auto_fetch_enabled": True}) == {"auto_fetch_enabled": True}
    assert validate({"auto_fetch_enabled": False}) == {"auto_fetch_enabled": False}


def test_validate_auto_fetch_enabled_non_bool_raises():
    with pytest.raises(AppSettingsError):
        validate({"auto_fetch_enabled": "yes"})


def test_validate_valid_auto_fetch_time():
    assert validate({"auto_fetch_time": "00:05"}) == {"auto_fetch_time": "00:05"}
    assert validate({"auto_fetch_time": "23:59"}) == {"auto_fetch_time": "23:59"}
    assert validate({"auto_fetch_time": "00:00"}) == {"auto_fetch_time": "00:00"}


def test_validate_auto_fetch_time_bad_format_raises():
    for bad in ["5:00", "24:00", "12:60", "noon", "12:00:00", ""]:
        with pytest.raises(AppSettingsError):
            validate({"auto_fetch_time": bad})


def test_validate_auto_fetch_time_not_a_string_raises():
    with pytest.raises(AppSettingsError):
        validate({"auto_fetch_time": 5})


def test_validate_multiple_fields_at_once():
    patch = {"auto_fetch_enabled": False, "auto_fetch_time": "03:30"}
    assert validate(patch) == patch


def test_validate_unknown_key_ignored():
    assert validate({"bogus": "value"}) == {}
