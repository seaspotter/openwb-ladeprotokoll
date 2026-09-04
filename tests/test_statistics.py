import pytest

from app.statistics import PeriodStats, StatisticsError, aggregate


def _session(
    time_begin, energy_kwh=10.0, cost_openwb=3.0, cost_used=3.0,
    grid=None, pv=None, bat=None, cp=None,
):
    return {
        "time_begin": time_begin,
        "energy_kwh": energy_kwh,
        "cost_openwb": cost_openwb,
        "cost_used": cost_used,
        "power_source_grid_pct": grid,
        "power_source_pv_pct": pv,
        "power_source_bat_pct": bat,
        "power_source_cp_pct": cp,
    }


def test_aggregate_empty_list():
    assert aggregate([]) == []


def test_aggregate_single_session_month():
    sessions = [_session("2026-08-15T10:00:00+00:00", energy_kwh=10.0, cost_used=3.5)]
    result = aggregate(sessions, granularity="month", cost_basis="corrected")
    assert result == [
        PeriodStats(
            period="2026-08", session_count=1, energy_kwh=10.0, cost=3.5,
            energy_grid_kwh=0.0, energy_pv_kwh=0.0, energy_bat_kwh=0.0, energy_cp_kwh=0.0,
        )
    ]


def test_aggregate_groups_by_year():
    sessions = [
        _session("2026-01-01T10:00:00+00:00", energy_kwh=5.0),
        _session("2026-08-15T10:00:00+00:00", energy_kwh=7.0),
        _session("2025-12-31T23:00:00+00:00", energy_kwh=3.0),
    ]
    result = aggregate(sessions, granularity="year")
    periods = {p.period: p for p in result}
    assert set(periods) == {"2025", "2026"}
    assert periods["2026"].energy_kwh == 12.0
    assert periods["2026"].session_count == 2
    assert periods["2025"].energy_kwh == 3.0


def test_aggregate_sorted_chronologically():
    sessions = [
        _session("2026-08-01T10:00:00+00:00"),
        _session("2026-01-01T10:00:00+00:00"),
        _session("2026-05-01T10:00:00+00:00"),
    ]
    result = aggregate(sessions, granularity="month")
    assert [p.period for p in result] == ["2026-01", "2026-05", "2026-08"]


def test_aggregate_energy_source_split_absolute_kwh_not_averaged_pct():
    # A 2 kWh session at 100% grid and a 40 kWh session at 100% PV --
    # summing absolute kWh gives grid=2, pv=40; naively averaging the two
    # sessions' percentages would have given a misleading 50/50 split.
    sessions = [
        _session("2026-08-01T10:00:00+00:00", energy_kwh=2.0, grid=100.0, pv=0.0),
        _session("2026-08-02T10:00:00+00:00", energy_kwh=40.0, grid=0.0, pv=100.0),
    ]
    result = aggregate(sessions, granularity="month")
    assert len(result) == 1
    p = result[0]
    assert p.energy_grid_kwh == 2.0
    assert p.energy_pv_kwh == 40.0
    assert p.energy_bat_kwh == 0.0
    assert p.energy_cp_kwh == 0.0


def test_aggregate_none_power_source_pct_treated_as_zero_contribution():
    sessions = [_session("2026-08-01T10:00:00+00:00", energy_kwh=10.0)]
    result = aggregate(sessions, granularity="month")
    p = result[0]
    assert p.energy_grid_kwh == 0.0
    assert p.energy_pv_kwh == 0.0


def test_aggregate_cost_basis_openwb_vs_corrected():
    sessions = [_session("2026-08-01T10:00:00+00:00", cost_openwb=3.0, cost_used=4.5)]
    openwb_result = aggregate(sessions, cost_basis="openwb")
    corrected_result = aggregate(sessions, cost_basis="corrected")
    assert openwb_result[0].cost == 3.0
    assert corrected_result[0].cost == 4.5


def test_aggregate_sessions_missing_time_begin_are_skipped():
    sessions = [
        _session("2026-08-01T10:00:00+00:00", energy_kwh=5.0),
        {"time_begin": None, "energy_kwh": 100.0},
    ]
    result = aggregate(sessions, granularity="month")
    assert len(result) == 1
    assert result[0].energy_kwh == 5.0


def test_aggregate_unknown_granularity_raises():
    with pytest.raises(StatisticsError):
        aggregate([], granularity="week")


def test_aggregate_unknown_cost_basis_raises():
    with pytest.raises(StatisticsError):
        aggregate([], cost_basis="bogus")
