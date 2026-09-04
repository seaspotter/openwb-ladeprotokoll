"""Report-wide display settings: which PDF columns are pre-selected by
default (the *only* place columns are chosen -- there is deliberately no
second, per-report column picker; an earlier version had one in the review
UI too and it was confusing to have the same choice in two places),
whether the single "Kosten" column/total shows openWB's own cost or the
price-corrected one, whether generated PDFs include the signature line,
page orientation, and the two global EUR/kWh rates (`pv_price_per_kwh`,
`bat_price_per_kwh`) `price_entries.corrected_cost` uses for the PV- and
battery-sourced share of a session's energy -- a `price_entries` row only
ever prices the grid-sourced share (see that module's docstring). A single
row in `report_settings` (id=1, enforced by a CHECK constraint) -- read
via GET, written via PUT `/api/report-settings` (see web.py), editable
from the Einstellungen modal (`_settings_modal.html`, included on every
page).

`validate()` is pure (no DB/HTTP) so it and its error messages are cheap
to unit test directly, matching this project's other *_entries.py-style
modules.
"""
from __future__ import annotations

from .report_build import COLUMN_LABELS, COST_BASES

ORIENTATIONS = ("portrait", "landscape")

# A lean starting set rather than "all columns" -- the fuller list a user
# can still opt into fits portrait A4 (the default orientation) much more
# comfortably; selecting most/all columns is exactly when landscape (also
# configurable here) earns its keep.
DEFAULT_COLUMNS: list[str] = ["begin", "end", "vehicle", "chargepoint", "energy", "cost"]
DEFAULT_COST_BASIS = "corrected"
DEFAULT_SHOW_SIGNATURE_LINE = False
DEFAULT_ORIENTATION = "portrait"
DEFAULT_PV_PRICE_PER_KWH = 0.0
DEFAULT_BAT_PRICE_PER_KWH = 0.0


class ReportSettingsError(ValueError):
    pass


def validate(patch: dict) -> dict:
    """Checks only the keys present in `patch` -- callers merge it onto the
    current settings, so a partial update (e.g. just `cost_basis`) doesn't
    need to already know the other fields' current values just to pass
    validation."""
    if "default_columns" in patch:
        cols = patch["default_columns"]
        if not isinstance(cols, list) or not cols:
            raise ReportSettingsError("default_columns muss eine nicht-leere Liste sein")
        unknown = [c for c in cols if c not in COLUMN_LABELS]
        if unknown:
            raise ReportSettingsError(f"Unbekannte Spalte(n): {unknown}")
    if "cost_basis" in patch and patch["cost_basis"] not in COST_BASES:
        raise ReportSettingsError(f"cost_basis muss einer von {COST_BASES} sein")
    if "show_signature_line" in patch and not isinstance(patch["show_signature_line"], bool):
        raise ReportSettingsError("show_signature_line muss ein Boolean sein")
    if "orientation" in patch and patch["orientation"] not in ORIENTATIONS:
        raise ReportSettingsError(f"orientation muss einer von {ORIENTATIONS} sein")
    for key in ("pv_price_per_kwh", "bat_price_per_kwh"):
        if key in patch:
            value = patch[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ReportSettingsError(f"{key} muss eine Zahl >= 0 sein")
    return patch


async def get_settings(pool) -> dict:
    row = await pool.fetchrow("SELECT * FROM report_settings WHERE id = 1")
    if row is None:
        row = await pool.fetchrow(
            "INSERT INTO report_settings "
            "(id, default_columns, cost_basis, show_signature_line, orientation, "
            "pv_price_per_kwh, bat_price_per_kwh) "
            "VALUES (1, $1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (id) DO UPDATE SET id = report_settings.id "
            "RETURNING *",
            DEFAULT_COLUMNS, DEFAULT_COST_BASIS, DEFAULT_SHOW_SIGNATURE_LINE, DEFAULT_ORIENTATION,
            DEFAULT_PV_PRICE_PER_KWH, DEFAULT_BAT_PRICE_PER_KWH,
        )
    return {
        "default_columns": row["default_columns"],
        "cost_basis": row["cost_basis"],
        "show_signature_line": row["show_signature_line"],
        "orientation": row["orientation"],
        "pv_price_per_kwh": float(row["pv_price_per_kwh"]),
        "bat_price_per_kwh": float(row["bat_price_per_kwh"]),
    }


async def update_settings(pool, patch: dict) -> dict:
    validate(patch)
    current = await get_settings(pool)
    merged = {**current, **patch}
    await pool.execute(
        "UPDATE report_settings SET default_columns = $1, cost_basis = $2, "
        "show_signature_line = $3, orientation = $4, pv_price_per_kwh = $5, "
        "bat_price_per_kwh = $6 WHERE id = 1",
        merged["default_columns"], merged["cost_basis"], merged["show_signature_line"],
        merged["orientation"], merged["pv_price_per_kwh"], merged["bat_price_per_kwh"],
    )
    return merged
