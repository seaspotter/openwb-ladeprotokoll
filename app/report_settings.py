"""Report-wide display settings: which PDF columns are pre-selected by
default in the review UI, whether the single "Kosten" column/total shows
openWB's own cost or the price-corrected one, and whether generated PDFs
include the signature line. A single row in `report_settings` (id=1,
enforced by a CHECK constraint) -- read via GET, written via PUT
`/api/report-settings` (see web.py), editable from the "Berichts-
Einstellungen" panel in settings.html.

`validate()` is pure (no DB/HTTP) so it and its error messages are cheap
to unit test directly, matching this project's other *_entries.py-style
modules.
"""
from __future__ import annotations

from .report_build import COLUMN_LABELS, COST_BASES

# A lean starting set rather than "all columns" -- the fuller list a user
# can still opt into via Berichts-Einstellungen fits portrait A4 (the
# default page orientation, see report_pdf.html) much more comfortably.
DEFAULT_COLUMNS: list[str] = ["begin", "end", "vehicle", "chargepoint", "energy", "cost"]
DEFAULT_COST_BASIS = "corrected"
DEFAULT_SHOW_SIGNATURE_LINE = False


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
    return patch


async def get_settings(pool) -> dict:
    row = await pool.fetchrow("SELECT * FROM report_settings WHERE id = 1")
    if row is None:
        row = await pool.fetchrow(
            "INSERT INTO report_settings (id, default_columns, cost_basis, show_signature_line) "
            "VALUES (1, $1, $2, $3) "
            "ON CONFLICT (id) DO UPDATE SET id = report_settings.id "
            "RETURNING *",
            DEFAULT_COLUMNS, DEFAULT_COST_BASIS, DEFAULT_SHOW_SIGNATURE_LINE,
        )
    return {
        "default_columns": row["default_columns"],
        "cost_basis": row["cost_basis"],
        "show_signature_line": row["show_signature_line"],
    }


async def update_settings(pool, patch: dict) -> dict:
    validate(patch)
    current = await get_settings(pool)
    merged = {**current, **patch}
    await pool.execute(
        "UPDATE report_settings SET default_columns = $1, cost_basis = $2, "
        "show_signature_line = $3 WHERE id = 1",
        merged["default_columns"], merged["cost_basis"], merged["show_signature_line"],
    )
    return merged
