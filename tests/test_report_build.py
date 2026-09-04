from datetime import date, datetime

import pytest

from app.report_build import (
    COLUMN_LABELS,
    DEFAULT_COLUMNS,
    ReportBuildError,
    build,
)


def _price_entry(provider="Stadtwerke", price_per_kwh=0.30,
                  valid_from=date(2026, 1, 1), valid_to=None, id=1):
    return {
        "id": id, "source_id": None, "vehicle_name": None, "provider": provider,
        "price_per_kwh": price_per_kwh, "valid_from": valid_from, "valid_to": valid_to,
        "notes": None, "created_at": datetime(2026, 1, 1),
    }


def _session(id=1, energy_kwh=10.0, cost_openwb=3.0, price_entry=None,
             cost_corrected=None, cost_used=None, delta_flagged=False,
             time_charged_seconds=3600, energy_discharged_kwh=0.0, range_charged_km=50.0):
    return {
        "id": id,
        "time_begin": datetime(2026, 8, 2, 8, 24, 55),
        "time_end": datetime(2026, 8, 2, 9, 22, 45),
        "time_charged_seconds": time_charged_seconds,
        "vehicle_name": "VW ID3",
        "odometer": 14611.0,
        "chargepoint_name": "Externe openWB",
        "chargepoint_serial_number": "241248169",
        "energy_kwh": energy_kwh,
        "energy_discharged_kwh": energy_discharged_kwh,
        "range_charged_km": range_charged_km,
        "meter_start_kwh": 1454.09,
        "meter_end_kwh": 1455.41,
        "cost_openwb": cost_openwb,
        "cost_corrected": cost_corrected,
        "cost_used": cost_used if cost_used is not None else (cost_corrected or cost_openwb),
        "price_entry": price_entry,
        "delta_flagged": delta_flagged,
    }


def test_default_columns_used_when_none_given():
    data = build([_session()])
    assert data.columns == DEFAULT_COLUMNS
    assert data.column_labels == [COLUMN_LABELS[c] for c in DEFAULT_COLUMNS]


def test_column_order_normalized_regardless_of_input_order():
    data = build([_session()], columns=["cost_openwb", "begin", "vehicle"])
    assert data.columns == ["begin", "vehicle", "cost_openwb"]


def test_unknown_column_raises():
    with pytest.raises(ReportBuildError):
        build([_session()], columns=["not_a_real_column"])


def test_empty_columns_raises():
    with pytest.raises(ReportBuildError):
        build([_session()], columns=[])


def test_cells_only_include_selected_columns():
    data = build([_session()], columns=["begin", "energy"])
    row = data.rows[0]
    assert set(row.cells.keys()) == {"begin", "energy"}
    assert row.cells["begin"] == "02.08.2026 08:24"
    assert row.cells["energy"] == "10,00 kWh"


def test_price_basis_cell_no_entry():
    data = build([_session(price_entry=None)], columns=["price_basis"])
    assert data.rows[0].cells["price_basis"] == "kein Preis hinterlegt"


def test_price_basis_cell_with_entry():
    entry = _price_entry(provider="Stadtwerke Musterstadt")
    data = build([_session(price_entry=entry)], columns=["price_basis"])
    assert data.rows[0].cells["price_basis"] == "Stadtwerke Musterstadt"


def test_totals_sum_across_sessions():
    s1 = _session(id=1, energy_kwh=10.0, cost_openwb=3.0, time_charged_seconds=3600,
                   energy_discharged_kwh=1.0, range_charged_km=50.0,
                   cost_used=3.0)
    s2 = _session(id=2, energy_kwh=5.0, cost_openwb=1.5, time_charged_seconds=1800,
                   energy_discharged_kwh=0.5, range_charged_km=20.0,
                   cost_used=1.5)
    data = build([s1, s2])
    assert data.totals.duration_seconds == 5400
    assert data.totals.energy_kwh == pytest.approx(15.0)
    assert data.totals.energy_discharged_kwh == pytest.approx(1.5)
    assert data.totals.range_charged_km == pytest.approx(70.0)
    assert data.totals.cost_openwb == pytest.approx(4.5)
    assert data.totals.cost_corrected == pytest.approx(4.5)
    assert data.totals.duration_display == "1:30"


def test_totals_use_cost_used_not_raw_cost_corrected_for_corrected_total():
    """A session with no price entry has cost_corrected=None but cost_used
    falls back to cost_openwb -- the "corrected" total must still include
    it via cost_used, not silently drop it because cost_corrected is None."""
    s1 = _session(id=1, energy_kwh=10.0, cost_openwb=3.0, price_entry=None,
                   cost_corrected=None, cost_used=3.0)
    entry = _price_entry(price_per_kwh=0.5)
    s2 = _session(id=2, energy_kwh=10.0, cost_openwb=3.0, price_entry=entry,
                   cost_corrected=5.0, cost_used=5.0)
    data = build([s1, s2])
    assert data.totals.cost_openwb == pytest.approx(6.0)
    assert data.totals.cost_corrected == pytest.approx(8.0)


def test_price_basis_deduplicates_and_counts_sessions():
    entry = _price_entry(provider="Stadtwerke", price_per_kwh=0.30,
                          valid_from=date(2026, 1, 1), valid_to=None)
    s1 = _session(id=1, price_entry=entry)
    s2 = _session(id=2, price_entry=entry)
    other_entry = _price_entry(provider="Anderer Anbieter", price_per_kwh=0.35, id=2)
    s3 = _session(id=3, price_entry=other_entry)
    data = build([s1, s2, s3])
    assert len(data.price_basis) == 2
    stadtwerke = next(p for p in data.price_basis if p.provider == "Stadtwerke")
    assert stadtwerke.session_count == 2
    anderer = next(p for p in data.price_basis if p.provider == "Anderer Anbieter")
    assert anderer.session_count == 1


def test_price_basis_empty_when_no_sessions_have_a_price_entry():
    data = build([_session(price_entry=None)])
    assert data.price_basis == []


def test_row_order_preserved():
    data = build([_session(id=3), _session(id=1), _session(id=2)])
    assert [r.session_id for r in data.rows] == [3, 1, 2]


def test_missing_optional_fields_render_as_dash():
    s = _session()
    s["time_end"] = None
    s["odometer"] = None
    data = build([s], columns=["end", "odometer"])
    assert data.rows[0].cells["end"] == "–"
    assert data.rows[0].cells["odometer"] == "–"


def test_duration_over_24_hours_formats_correctly():
    """Matches openWB's own "H:MM" display for a multi-day session, see
    chargelog_parse.py -- 35h02m stays "35:02", not wrapping to a day+hour
    format."""
    s = _session(time_charged_seconds=35 * 3600 + 2 * 60)
    data = build([s], columns=["duration"])
    assert data.rows[0].cells["duration"] == "35:02"
