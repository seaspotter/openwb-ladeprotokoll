import pytest

from app.sources import SourceValidationError, normalize_base_url, validate_name


def test_normalize_bare_ip_defaults_to_http():
    assert normalize_base_url("192.168.1.10") == "http://192.168.1.10"


def test_normalize_ip_with_port():
    assert normalize_base_url("192.168.1.10:8080") == "http://192.168.1.10:8080"


def test_normalize_full_url_strips_trailing_slash_and_path():
    assert normalize_base_url("http://192.168.1.10/") == "http://192.168.1.10"


def test_normalize_preserves_https():
    assert normalize_base_url("https://openwb.local") == "https://openwb.local"


def test_normalize_hostname():
    assert normalize_base_url("openwb.local") == "http://openwb.local"


def test_normalize_empty_raises():
    with pytest.raises(SourceValidationError):
        normalize_base_url("   ")


def test_normalize_unsupported_scheme_raises():
    with pytest.raises(SourceValidationError):
        normalize_base_url("ftp://openwb.local")


def test_normalize_no_hostname_raises():
    with pytest.raises(SourceValidationError):
        normalize_base_url("http://")


def test_validate_name_strips_whitespace():
    assert validate_name("  Zuhause  ") == "Zuhause"


def test_validate_name_empty_raises():
    with pytest.raises(SourceValidationError):
        validate_name("   ")
