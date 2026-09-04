from datetime import date, datetime

import pytest

from app.price_entries import (
    DELTA_FLAG_THRESHOLD,
    corrected_cost,
    decide_price,
    match_and_decide,
    match_price_entry,
)


def _entry(id, source_id=None, vehicle_name=None, price_per_kwh=0.30,
           valid_from=date(2026, 1, 1), valid_to=None, created_at=None):
    return {
        "id": id,
        "source_id": source_id,
        "vehicle_name": vehicle_name,
        "provider": "Test Provider",
        "price_per_kwh": price_per_kwh,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "notes": None,
        "created_at": created_at or datetime(2026, 1, 1, 12, 0, 0),
    }


def test_match_no_entries_returns_none():
    result = match_price_entry(
        [], source_id=1, vehicle_name="VW ID3", session_date=date(2026, 8, 2)
    )
    assert result is None


def test_match_wildcard_entry_applies_to_anything():
    wildcard = _entry(1)
    result = match_price_entry(
        [wildcard], source_id=1, vehicle_name="VW ID3", session_date=date(2026, 8, 2)
    )
    assert result == wildcard


def test_match_specificity_source_and_vehicle_beats_source_only():
    source_only = _entry(1, source_id=1)
    both = _entry(2, source_id=1, vehicle_name="VW ID3")
    result = match_price_entry(
        [source_only, both], source_id=1, vehicle_name="VW ID3", session_date=date(2026, 8, 2)
    )
    assert result == both


def test_match_specificity_source_only_beats_vehicle_only():
    source_only = _entry(1, source_id=1)
    vehicle_only = _entry(2, vehicle_name="VW ID3")
    result = match_price_entry(
        [source_only, vehicle_only], source_id=1, vehicle_name="VW ID3",
        session_date=date(2026, 8, 2),
    )
    assert result == source_only


def test_match_specificity_vehicle_only_beats_wildcard():
    vehicle_only = _entry(1, vehicle_name="VW ID3")
    wildcard = _entry(2)
    result = match_price_entry(
        [vehicle_only, wildcard], source_id=1, vehicle_name="VW ID3",
        session_date=date(2026, 8, 2),
    )
    assert result == vehicle_only


def test_match_tie_break_by_most_recent_created_at():
    older = _entry(1, source_id=1, created_at=datetime(2026, 1, 1))
    newer = _entry(2, source_id=1, created_at=datetime(2026, 6, 1))
    result = match_price_entry(
        [older, newer], source_id=1, vehicle_name=None, session_date=date(2026, 8, 2)
    )
    assert result == newer


def test_match_wrong_source_excluded():
    entry = _entry(1, source_id=2)
    result = match_price_entry(
        [entry], source_id=1, vehicle_name=None, session_date=date(2026, 8, 2)
    )
    assert result is None


def test_match_wrong_vehicle_excluded():
    entry = _entry(1, vehicle_name="Renault Megane")
    result = match_price_entry(
        [entry], source_id=1, vehicle_name="VW ID3", session_date=date(2026, 8, 2)
    )
    assert result is None


def test_match_before_valid_from_excluded():
    entry = _entry(1, valid_from=date(2026, 9, 1))
    result = match_price_entry(
        [entry], source_id=1, vehicle_name=None, session_date=date(2026, 8, 2)
    )
    assert result is None


def test_match_after_valid_to_excluded():
    entry = _entry(1, valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))
    result = match_price_entry(
        [entry], source_id=1, vehicle_name=None, session_date=date(2026, 8, 2)
    )
    assert result is None


def test_match_open_ended_valid_to_applies_indefinitely():
    entry = _entry(1, valid_from=date(2026, 1, 1), valid_to=None)
    result = match_price_entry(
        [entry], source_id=1, vehicle_name=None, session_date=date(2030, 1, 1)
    )
    assert result == entry


def test_corrected_cost():
    assert corrected_cost(9.7, 0.30) == pytest.approx(2.91)


def test_corrected_cost_none_energy_returns_none():
    assert corrected_cost(None, 0.30) is None


def test_decide_price_no_entry_falls_back_to_openwb_cost():
    decision = decide_price(energy_kwh=9.7, cost_openwb=4.50, price_entry=None)
    assert decision.cost_corrected is None
    assert decision.cost_used == 4.50
    assert decision.delta is None
    assert decision.delta_flagged is False


def test_decide_price_with_entry_flags_delta_above_threshold():
    entry = _entry(1, price_per_kwh=0.30)
    # energy_kwh=9.7 * 0.30 = 2.91, vs. openWB's 4.50 -> delta well above threshold
    decision = decide_price(energy_kwh=9.7, cost_openwb=4.50, price_entry=entry)
    assert decision.cost_corrected == pytest.approx(2.91)
    assert decision.cost_used == pytest.approx(2.91)
    assert decision.delta == pytest.approx(2.91 - 4.50)
    assert decision.delta_flagged is True


def test_decide_price_delta_below_threshold_not_flagged():
    entry = _entry(1, price_per_kwh=0.30)
    cost_openwb = 9.7 * 0.30 + (DELTA_FLAG_THRESHOLD / 2)
    decision = decide_price(energy_kwh=9.7, cost_openwb=cost_openwb, price_entry=entry)
    assert decision.delta_flagged is False


def test_match_and_decide_end_to_end():
    entry = _entry(1, source_id=1, vehicle_name="VW ID3", price_per_kwh=0.35)
    decision = match_and_decide(
        [entry], source_id=1, vehicle_name="VW ID3", session_date=date(2026, 8, 2),
        energy_kwh=10.0, cost_openwb=3.0,
    )
    assert decision.price_entry == entry
    assert decision.cost_corrected == 3.5
    assert decision.cost_used == 3.5


def test_decide_price_grid_only_prices_only_the_grid_share():
    entry = _entry(1, price_per_kwh=0.30)
    decision = decide_price(energy_kwh=10.0, cost_openwb=1.0, price_entry=entry, grid_pct=40.0)
    # 10 kWh total, 40% grid -> 4 kWh grid-priced at 0.30 = 1.20
    assert decision.cost_corrected_grid_only == pytest.approx(1.20)
    # total-energy figures are unaffected by grid_pct
    assert decision.cost_corrected == pytest.approx(3.0)


def test_decide_price_grid_only_missing_pct_assumes_100_percent_grid():
    entry = _entry(1, price_per_kwh=0.30)
    decision = decide_price(energy_kwh=10.0, cost_openwb=1.0, price_entry=entry, grid_pct=None)
    assert decision.cost_corrected_grid_only == pytest.approx(3.0)
    assert decision.cost_corrected_grid_only == decision.cost_corrected


def test_decide_price_grid_only_no_entry_falls_back_to_openwb():
    decision = decide_price(energy_kwh=10.0, cost_openwb=4.5, price_entry=None, grid_pct=40.0)
    assert decision.cost_corrected_grid_only is None
    assert decision.cost_used_grid_only == 4.5


def test_decide_price_grid_only_zero_percent_grid_is_free():
    entry = _entry(1, price_per_kwh=0.30)
    decision = decide_price(energy_kwh=10.0, cost_openwb=1.0, price_entry=entry, grid_pct=0.0)
    assert decision.cost_corrected_grid_only == 0.0
    assert decision.cost_used_grid_only == 0.0


def test_match_and_decide_passes_grid_pct_through():
    entry = _entry(1, source_id=1, vehicle_name="VW ID3", price_per_kwh=0.30)
    decision = match_and_decide(
        [entry], source_id=1, vehicle_name="VW ID3", session_date=date(2026, 8, 2),
        energy_kwh=10.0, cost_openwb=1.0, grid_pct=50.0,
    )
    assert decision.cost_corrected_grid_only == pytest.approx(1.5)
