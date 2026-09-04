from datetime import datetime

import pytest

from app.chargelog_parse import ChargeLogParseError, natural_key, parse_record

# Real record from a live openWB installation's chargelog-202608.json
# (shared 2026-09-03), used verbatim so the parser is checked against
# actual wire values, not a guess at their shape.
REAL_RECORD = {
    "chargepoint": {
        "id": 5, "name": "Externe openWB", "serial_number": "241248169",
        "imported_at_start": 1454094.97, "imported_at_end": 1455412.96,
        "exported_at_start": 0, "exported_at_end": 0,
    },
    "vehicle": {
        "id": 2, "name": "VW ID3", "chargemode": "pv_charging", "prio": False,
        "rfid": None, "odometer": 14611.0, "soc_at_start": 49.0, "soc_at_end": 50.42,
        "range_at_start": 241, "range_at_end": 248,
    },
    "time": {
        "begin": "08/02/2026, 08:24:55", "end": "08/02/2026, 09:22:45", "time_charged": "0:44",
    },
    "data": {
        "range_charged": 7, "exported_since_mode_switch": 0, "exported_since_plugged": 0,
        "imported_since_mode_switch": 1317.99, "imported_since_plugged": 1317.99,
        "power": 1784.71, "costs": 0.36,
        "power_source": {
            "bat": 0.11067170411338259, "cp": 0.0, "grid": 0.0, "pv": 0.7527035870496197,
        },
    },
}

# A second real record from the same file, for a session split across a
# charge-mode switch: imported_since_mode_switch (per-row) and
# imported_since_plugged (cumulative) differ, which is exactly the
# distinction that was previously coded backwards.
REAL_RECORD_MODE_SWITCH = {
    "chargepoint": {
        "id": 4, "name": "Interne openWB", "serial_number": "20074098",
        "imported_at_start": 11517800.78, "imported_at_end": 11523118.16,
        "exported_at_start": 0, "exported_at_end": 0,
    },
    "vehicle": {
        "id": 1, "name": "Renault Megane", "chargemode": "pv_charging", "prio": False,
        "rfid": None, "odometer": 47477.0, "soc_at_start": 86.0, "soc_at_end": 94.0,
        "range_at_start": 345.0, "range_at_end": 377.0,
    },
    "time": {
        "begin": "08/06/2026, 14:38:49", "end": "08/06/2026, 17:08:45", "time_charged": "2:16",
    },
    "data": {
        "range_charged": 32.0, "exported_since_mode_switch": 0, "exported_since_plugged": 0,
        "imported_since_mode_switch": 5317.38, "imported_since_plugged": 6068.36,
        "power": 2334.86, "costs": 1.44,
        "power_source": {
            "bat": 0.03567471198219506, "cp": 0.0, "grid": 0.0, "pv": 0.9202509506557376,
        },
    },
}


def test_parse_real_record():
    row = parse_record(REAL_RECORD)
    assert row["chargepoint_serial_number"] == "241248169"
    assert row["chargepoint_name"] == "Externe openWB"
    assert row["vehicle_name"] == "VW ID3"
    assert row["vehicle_chargemode"] == "pv_charging"
    assert row["vehicle_prio"] == "false"
    assert row["time_begin"] == datetime(2026, 8, 2, 8, 24, 55)
    assert row["time_end"] == datetime(2026, 8, 2, 9, 22, 45)
    assert row["time_charged_seconds"] == 44 * 60
    assert row["cost_openwb"] == 0.36
    # Wh -> kWh conversion.
    assert row["energy_kwh"] == pytest.approx(1.31799)
    assert row["energy_since_plugged_kwh"] == pytest.approx(1.31799)
    assert row["energy_discharged_kwh"] == 0.0
    assert row["meter_start_kwh"] == pytest.approx(1454.09497)
    assert row["meter_end_kwh"] == pytest.approx(1455.41296)
    # fraction -> percentage conversion.
    assert row["power_source_bat_pct"] == pytest.approx(11.067170411338259)
    assert row["power_source_pv_pct"] == pytest.approx(75.27035870496197)
    assert row["power_source_grid_pct"] == 0.0
    assert row["range_charged_km"] == 7
    assert row["raw_json"] == REAL_RECORD


def test_parse_real_record_mode_switch_energy_is_not_cumulative():
    """The per-row "Energie" figure (energy_kwh) must come from
    imported_since_mode_switch, not the cumulative imported_since_plugged
    -- this real record has the two differ (5317.38 Wh vs 6068.36 Wh),
    which a swapped mapping would silently get backwards."""
    row = parse_record(REAL_RECORD_MODE_SWITCH)
    assert row["energy_kwh"] == pytest.approx(5.31738)
    assert row["energy_since_plugged_kwh"] == pytest.approx(6.06836)
    assert row["energy_kwh"] != row["energy_since_plugged_kwh"]


def test_parse_still_charging_record_has_no_end_time():
    record = {
        **REAL_RECORD,
        "time": {"begin": "08/02/2026, 08:24:55", "end": None, "time_charged": None},
    }
    row = parse_record(record)
    assert row["time_end"] is None
    assert row["time_charged_seconds"] is None


def test_parse_missing_odometer_dash_is_none():
    record = {
        **REAL_RECORD,
        "vehicle": {**REAL_RECORD["vehicle"], "odometer": "-km"},
    }
    row = parse_record(record)
    assert row["odometer"] is None


def test_parse_missing_serial_number_raises():
    record = {
        **REAL_RECORD,
        "chargepoint": {**REAL_RECORD["chargepoint"], "serial_number": None},
    }
    with pytest.raises(ChargeLogParseError):
        parse_record(record)


def test_parse_isoformat_timestamp():
    record = {
        **REAL_RECORD,
        "time": {"begin": "2026-08-01T08:00:00", "end": None, "time_charged": None},
    }
    row = parse_record(record)
    assert row["time_begin"] == datetime(2026, 8, 1, 8, 0, 0)


def test_parse_epoch_timestamp():
    """Defensive fallback only -- real data uses "MM/DD/YYYY, HH:MM:SS"
    strings (see test_parse_real_record), not epoch numbers, but this is
    kept in case a different openWB version emits one."""
    epoch = int(datetime(2026, 8, 1, 8, 0, 0).timestamp())
    record = {
        **REAL_RECORD,
        "time": {"begin": epoch, "end": None, "time_charged": None},
    }
    row = parse_record(record)
    assert row["time_begin"] == datetime.fromtimestamp(epoch)


def test_parse_german_formatted_timestamp():
    """Defensive fallback for a DD.MM.YYYY variant, in case it's used by a
    different openWB version/locale than the confirmed MM/DD/YYYY one."""
    record = {
        **REAL_RECORD,
        "time": {"begin": "01.08.2026, 08:00:00", "end": None, "time_charged": None},
    }
    row = parse_record(record)
    assert row["time_begin"] == datetime(2026, 8, 1, 8, 0, 0)


def test_parse_duration_hours_minutes_no_seconds():
    """Real format: "H:MM", including values over 24 hours for a session
    that stays plugged in (charging paused) across multiple days."""
    record = {
        **REAL_RECORD,
        "time": {"begin": "08/02/2026, 08:24:55", "end": None, "time_charged": "35:02"},
    }
    row = parse_record(record)
    assert row["time_charged_seconds"] == 35 * 3600 + 2 * 60


def test_parse_duration_explicit_hms_fallback():
    record = {
        **REAL_RECORD,
        "time": {"begin": "08/02/2026, 08:24:55", "end": None, "time_charged": "1:02:03"},
    }
    row = parse_record(record)
    assert row["time_charged_seconds"] == 1 * 3600 + 2 * 60 + 3


def test_parse_duration_as_plain_seconds():
    record = {
        **REAL_RECORD,
        "time": {"begin": "08/02/2026, 08:24:55", "end": None, "time_charged": 5400},
    }
    row = parse_record(record)
    assert row["time_charged_seconds"] == 5400


def test_parse_prio_true():
    record = {**REAL_RECORD, "vehicle": {**REAL_RECORD["vehicle"], "prio": True}}
    row = parse_record(record)
    assert row["vehicle_prio"] == "true"


def test_natural_key():
    key = natural_key(source_id=1, record=REAL_RECORD)
    assert key == (1, "241248169", datetime(2026, 8, 2, 8, 24, 55))


def test_natural_key_missing_serial_raises():
    record = {**REAL_RECORD, "chargepoint": {"id": 1}}
    with pytest.raises(ChargeLogParseError):
        natural_key(source_id=1, record=record)
