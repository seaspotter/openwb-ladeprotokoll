"""Report-wide display settings: PDF columns (the only place they're
chosen), cost basis, orientation, signature line, the PV/battery EUR/kWh
rates (see price_entries.py), and digital-signing config (see
pdf_signing.py). A single row in `report_settings` (id=1), read/written
via `/api/report-settings` (web.py), editable from the Einstellungen
modal.

`get_settings()` never returns `sign_pdf_private_key_pem` -- that's this
install's whole signing identity, and the JSON route returns this dict
wholesale. `get_signing_key_pem()` is the one dedicated accessor for the
caller that actually needs it (web.py's `_generate_report`).
`regenerate_certificate()`/`ensure_certificate()` are the only writers of
the cert/key columns; `update_settings()`'s general patch path never
touches them.

`validate()` is pure, unit tested directly.
"""
from __future__ import annotations

from .pdf_signing import generate_self_signed_cert
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
DEFAULT_SIGN_PDF_ENABLED = False


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
    if "sign_pdf_enabled" in patch and not isinstance(patch["sign_pdf_enabled"], bool):
        raise ReportSettingsError("sign_pdf_enabled muss ein Boolean sein")
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
            "pv_price_per_kwh, bat_price_per_kwh, sign_pdf_enabled) "
            "VALUES (1, $1, $2, $3, $4, $5, $6, $7) "
            "ON CONFLICT (id) DO UPDATE SET id = report_settings.id "
            "RETURNING *",
            DEFAULT_COLUMNS, DEFAULT_COST_BASIS, DEFAULT_SHOW_SIGNATURE_LINE, DEFAULT_ORIENTATION,
            DEFAULT_PV_PRICE_PER_KWH, DEFAULT_BAT_PRICE_PER_KWH, DEFAULT_SIGN_PDF_ENABLED,
        )
    return {
        "default_columns": row["default_columns"],
        "cost_basis": row["cost_basis"],
        "show_signature_line": row["show_signature_line"],
        "orientation": row["orientation"],
        "pv_price_per_kwh": float(row["pv_price_per_kwh"]),
        "bat_price_per_kwh": float(row["bat_price_per_kwh"]),
        "sign_pdf_enabled": row["sign_pdf_enabled"],
        "sign_pdf_certificate_pem": row["sign_pdf_certificate_pem"],
        "sign_pdf_cert_created_at": row["sign_pdf_cert_created_at"],
    }


async def update_settings(pool, patch: dict) -> dict:
    validate(patch)
    current = await get_settings(pool)
    merged = {**current, **patch}
    await pool.execute(
        "UPDATE report_settings SET default_columns = $1, cost_basis = $2, "
        "show_signature_line = $3, orientation = $4, pv_price_per_kwh = $5, "
        "bat_price_per_kwh = $6, sign_pdf_enabled = $7 WHERE id = 1",
        merged["default_columns"], merged["cost_basis"], merged["show_signature_line"],
        merged["orientation"], merged["pv_price_per_kwh"], merged["bat_price_per_kwh"],
        merged["sign_pdf_enabled"],
    )
    return merged


async def get_signing_key_pem(pool) -> str | None:
    """The one place `sign_pdf_private_key_pem` is ever read back out --
    callers outside _generate_report's own signing step shouldn't need
    this; see the module docstring for why it's not in get_settings()."""
    row = await pool.fetchrow(
        "SELECT sign_pdf_private_key_pem FROM report_settings WHERE id = 1"
    )
    return row["sign_pdf_private_key_pem"] if row else None


async def regenerate_certificate(pool) -> dict:
    """Generates a fresh self-signed cert/key pair and overwrites the
    stored one unconditionally -- used both for the first-ever cert (via
    ensure_certificate) and an explicit user-triggered "Neues Zertifikat
    erzeugen" (web.py has its own hx-confirm warning that this invalidates
    trust in whatever recipients trusted before)."""
    await get_settings(pool)  # upsert-on-first-read, same as elsewhere
    cert_pem, key_pem = generate_self_signed_cert()
    await pool.execute(
        "UPDATE report_settings SET sign_pdf_certificate_pem = $1, "
        "sign_pdf_private_key_pem = $2, sign_pdf_cert_created_at = now() WHERE id = 1",
        cert_pem, key_pem,
    )
    return await get_settings(pool)


async def ensure_certificate(pool) -> dict:
    """Generates a cert/key pair only if none exists yet -- called when
    sign_pdf_enabled flips to True, so enabling always has a usable
    certificate immediately rather than silently signing nothing until
    someone separately clicks "Neues Zertifikat erzeugen"."""
    current = await get_settings(pool)
    if current["sign_pdf_certificate_pem"] is None:
        return await regenerate_certificate(pool)
    return current
