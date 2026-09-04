"""Pure parsing of one raw `data/charge_log/<yyyymm>.json` record (as served
by openWB, see openwb_client.py) into a normalized row ready for the
`sessions` table (see db.py) plus its natural key.

Confirmed record shape, cross-checked twice against real data from the same
openWB installation (2026-09-03): first against a CSV export of the
Ladeprotokoll UI, then against an actual `chargelog-202608.json` file. The
second pass overturned one assumption from the first (time.begin/end's wire
type) and caught two unit bugs the CSV alone couldn't reveal (CSV values are
already unit-converted for display):

    chargepoint{id, name, serial_number,
                imported_at_start, imported_at_end,   # Wh, cumulative meter reading
                exported_at_start, exported_at_end}   # Wh, V2H/V2G feed-back meter reading
    vehicle{id, name, chargemode, prio,               # prio is a bool, not a priority tier
            rfid, soc_at_start, soc_at_end,
            range_at_start, range_at_end, odometer}
    time{begin, end,           # "MM/DD/YYYY, HH:MM:SS" strings, e.g. "08/02/2026, 08:24:55"
         time_charged}         # "H:MM" (no seconds), e.g. "23:18", "35:02" for a >24h span
    data{costs,                # EUR, already in the display unit -- no conversion
         power_source{grid, cp, bat, pv},  # FRACTIONS 0.0-1.0, not already a percentage
         imported_since_mode_switch,   # Wh, per-row -- this is the UI's "Energie" column
         imported_since_plugged,       # Wh, cumulative since plug-in -- "Energie seit Anstecken"
         exported_since_mode_switch,   # Wh, per-row V2H/V2G discharge (0 if unused)
         exported_since_plugged,       # Wh, cumulative V2H/V2G discharge
         range_charged,        # km, already in the display unit
         power}                # instantaneous charging power in W -- not currently persisted

Two corrections from the CSV cross-check, both load-bearing for report
correctness (see git history / CHANGELOG for the incident):

- **"Energie" (the UI's headline per-row kWh figure, the one that should be
  summed for a report total) is data.imported_since_mode_switch, not
  imported_since_plugged.** A single plug-in that switches charge mode
  (e.g. Sofort -> PV) produces multiple consecutive charge-log rows;
  imported_since_plugged is the *cumulative* total across all of them.
  Summing the cumulative field across a session's rows would silently
  double- (or triple-, ...) count energy. energy_kwh below is the per-row
  figure; energy_since_plugged_kwh is the cumulative one, kept for
  reference/audit but must never be summed across rows of the same
  plug-in.
- **time.time_charged is "H:MM" (hours:minutes), not "H:MM:SS".** Values
  like "23:18" or "35:02" (over 24) are common (a session can stay plugged
  in, with charging paused, across several calendar days).

Two more corrections from the raw-JSON cross-check (the CSV export already
had these converted, so it couldn't reveal them):

- **Energy figures are in Wh, not kWh.** `imported_since_mode_switch`,
  `imported_since_plugged`, `exported_since_mode_switch`, and the
  chargepoint meter readings (`imported_at_start`/`imported_at_end`) are
  all watt-hours; every `_kwh`-suffixed field below divides by 1000.
- **power_source shares are fractions (0.0-1.0), not percentages.** The
  CSV's "Energieanteil ..." percentage columns are the raw fraction times
  100 for display; `_pct`-suffixed fields below apply that same ×100.

Still unconfirmed: `vehicle.prio`'s real-world value range beyond the
plain booleans seen so far (stored as the lowercase strings "true"/"false",
not Python's "True"/"False", to keep the DB free of a language-specific
repr); and any record where a V2H/V2G-capable vehicle actually produces a
nonzero `exported_since_mode_switch` (every sample seen has 0 there).
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


def natural_key(source_id: int, record: dict) -> tuple[int, str, datetime]:
    chargepoint = record.get("chargepoint") or {}
    time_block = record.get("time") or {}
    serial = chargepoint.get("serial_number")
    if not serial:
        raise ChargeLogParseError("Record is missing chargepoint.serial_number")
    begin = _parse_timestamp(time_block.get("begin"), field="time.begin")
    return (source_id, str(serial), begin)


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
