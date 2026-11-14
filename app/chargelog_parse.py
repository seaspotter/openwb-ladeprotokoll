"""Pure parsing of one raw `data/charge_log/<yyyymm>.json` record (as served
by openWB, see openwb_client.py) into a normalized row for the `sessions`
table (see db.py).

Record shape and load-bearing unit/field notes:

    chargepoint{id, name, serial_number,
                imported_at_start, imported_at_end,   # Wh, cumulative meter
                exported_at_start, exported_at_end}   # Wh, V2H/V2G meter
    vehicle{id, name, chargemode, prio,     # prio: bool, not a tier
            rfid, soc_at_start, soc_at_end,
            range_at_start, range_at_end, odometer}
    time{begin, end,           # "MM/DD/YYYY, HH:MM:SS"
         time_charged}         # "H:MM", no seconds, can exceed 24h
    data{costs,                            # EUR, display unit, no conversion
         power_source{grid, cp, bat, pv},   # fractions 0.0-1.0, not %
         imported_since_mode_switch,   # Wh, per-row -- UI's "Energie" column
         imported_since_plugged,       # Wh, cumulative since plug-in
         exported_since_mode_switch,   # Wh, per-row V2H/V2G (0 if unused)
         exported_since_plugged,       # Wh, cumulative V2H/V2G
         range_charged,        # km, display unit
         power}                # instantaneous W, not persisted

Sum `imported_since_mode_switch` (per-row) for a report total, never
`imported_since_plugged` (cumulative since plug-in) -- a mode-switching
plug-in produces multiple rows, so summing the cumulative field double-
counts energy. Energy fields are Wh (every `_kwh` field below divides by
1000); power_source shares are fractions (`_pct` fields below multiply by
100). `vehicle.prio` is stored as the lowercase string "true"/"false", not
Python's repr.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict


class ChargeLogParseError(ValueError):
    pass


class ParsedSession(TypedDict):
    chargepoint_id: str | None
    chargepoint_name: str | None
    chargepoint_serial_number: str
    vehicle_id: str | None
    vehicle_name: str | None
    vehicle_chargemode: str | None
    vehicle_prio: str | None
    vehicle_rfid: str | None
    soc_at_start: float | None
    soc_at_end: float | None
    range_at_start: float | None
    range_at_end: float | None
    odometer: float | None
    time_begin: datetime
    time_end: datetime | None
    time_charged_seconds: int | None
    cost_openwb: float | None
    power_source_grid_pct: float | None
    power_source_cp_pct: float | None
    power_source_bat_pct: float | None
    power_source_pv_pct: float | None
    energy_kwh: float | None
    energy_since_plugged_kwh: float | None
    energy_discharged_kwh: float | None
    range_charged_km: float | None
    meter_start_kwh: float | None
    meter_end_kwh: float | None
    raw_json: dict


def _num(value: Any) -> float | None:
    """Tolerant numeric coercion: openWB's UI shows missing numbers as "-"
    or "-km" (see the Ladeprotokoll odometer column), so a bare "-" or
    empty string is treated as "no value" rather than a parse error."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    text = text.rstrip("kKmM").strip()  # trailing unit, e.g. "42000km"
    if text in ("", "-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _wh_to_kwh(value: Any) -> float | None:
    n = _num(value)
    return None if n is None else n / 1000.0


def _fraction_to_pct(value: Any) -> float | None:
    n = _num(value)
    return None if n is None else n * 100.0


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        for fmt in ("%m/%d/%Y, %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y, %H:%M:%S",
                    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    raise ChargeLogParseError(f"Unparseable timestamp in {field!r}: {value!r}")


def _parse_optional_timestamp(value: Any, *, field: str) -> datetime | None:
    if value in (None, "", "-"):
        return None
    return _parse_timestamp(value, field=field)


def _parse_duration_seconds(value: Any) -> int | None:
    """"H:MM" is the confirmed real format (openWB's Ladeprotokoll "Dauer"
    column, e.g. "23:18", "35:02" for a >24h span) -- no seconds component.
    An explicit three-part "H:MM:SS" is also accepted defensively, in case
    a different openWB version ever emits one."""
    if value in (None, "", "-"):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if ":" in text:
        parts = text.split(":")
        try:
            parts = [int(p) for p in parts]
        except ValueError:
            return None
        if len(parts) == 2:
            hours, minutes = parts
            seconds = 0
        elif len(parts) == 3:
            hours, minutes, seconds = parts
        else:
            return None
        return hours * 3600 + minutes * 60 + seconds
    try:
        return int(float(text))
    except ValueError:
        return None


def _bool_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_record(record: dict) -> ParsedSession:
    chargepoint = record.get("chargepoint") or {}
    vehicle = record.get("vehicle") or {}
    time_block = record.get("time") or {}
    data = record.get("data") or {}
    power_source = data.get("power_source") or {}

    serial = chargepoint.get("serial_number")
    if not serial:
        raise ChargeLogParseError("Record is missing chargepoint.serial_number")

    return ParsedSession(
        chargepoint_id=(
            str(chargepoint["id"]) if chargepoint.get("id") is not None else None
        ),
        chargepoint_name=chargepoint.get("name"),
        chargepoint_serial_number=str(serial),
        vehicle_id=(str(vehicle["id"]) if vehicle.get("id") is not None else None),
        vehicle_name=vehicle.get("name"),
        vehicle_chargemode=vehicle.get("chargemode"),
        vehicle_prio=_bool_str(vehicle.get("prio")),
        vehicle_rfid=vehicle.get("rfid"),
        soc_at_start=_num(vehicle.get("soc_at_start")),
        soc_at_end=_num(vehicle.get("soc_at_end")),
        range_at_start=_num(vehicle.get("range_at_start")),
        range_at_end=_num(vehicle.get("range_at_end")),
        odometer=_num(vehicle.get("odometer")),
        time_begin=_parse_timestamp(time_block.get("begin"), field="time.begin"),
        time_end=_parse_optional_timestamp(time_block.get("end"), field="time.end"),
        time_charged_seconds=_parse_duration_seconds(time_block.get("time_charged")),
        cost_openwb=_num(data.get("costs")),
        power_source_grid_pct=_fraction_to_pct(power_source.get("grid")),
        power_source_cp_pct=_fraction_to_pct(power_source.get("cp")),
        power_source_bat_pct=_fraction_to_pct(power_source.get("bat")),
        power_source_pv_pct=_fraction_to_pct(power_source.get("pv")),
        energy_kwh=_wh_to_kwh(data.get("imported_since_mode_switch")),
        energy_since_plugged_kwh=_wh_to_kwh(data.get("imported_since_plugged")),
        energy_discharged_kwh=_wh_to_kwh(data.get("exported_since_mode_switch")),
        range_charged_km=_num(data.get("range_charged")),
        meter_start_kwh=_wh_to_kwh(chargepoint.get("imported_at_start")),
        meter_end_kwh=_wh_to_kwh(chargepoint.get("imported_at_end")),
        raw_json=record,
    )
