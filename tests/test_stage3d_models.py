from __future__ import annotations

from typing import Any

from polymarket_edge_lab.analysis.stage3d_models import (
    FEATURE_SETS,
    evaluate_held_out,
    summarize_results,
)


def _row(window: str, cost: float, offset: float) -> dict[str, Any]:
    return {
        "window_id": window,
        "pair_cost": cost,
        "paired_shares": 10.0,
        "favorable": cost < 1.0,
        "lag_seconds": 30.0 + offset,
        "elapsed_seconds": 120.0 + offset,
        "seconds_remaining": 180.0 - offset,
        "up_inventory": 20.0 + offset,
        "down_inventory": 18.0 + offset,
        "paired_inventory": 18.0 + offset,
        "residual_inventory": 2.0,
        "inventory_imbalance": 0.05,
        "seconds_since_last_up_fill": 3.0,
        "seconds_since_last_down_fill": 5.0,
        "fill_count_15s": 2.0,
        "fill_count_30s": 3.0,
        "fill_count_60s": 5.0,
        "fill_qty_15s": 4.0,
        "fill_qty_30s": 6.0,
        "fill_qty_60s": 10.0,
        "side_switches_60s": 2.0,
        "cumulative_paired_quantity": 15.0 + offset,
        "same_second_fill_count": 1.0,
        "btc_return_60s": 0.001 * offset,
        "btc_return_120s": 0.002 * offset,
        "btc_absolute_return_60s": abs(0.001 * offset),
        "btc_return_since_market_start": 0.003 * offset,
        "btc_range_since_market_start": 0.004 + 0.0001 * offset,
        "cumulative_up_vwap": 0.49,
        "cumulative_down_vwap": 0.50,
        "implied_complete_set_cost": 0.99,
    }


def test_primary_feature_sets_exclude_contemporaneous_price_state() -> None:
    primary = {feature for features in FEATURE_SETS.values() for feature in features}
    assert "cumulative_up_vwap" not in primary
    assert "cumulative_down_vwap" not in primary
    assert "implied_complete_set_cost" not in primary


def test_evaluate_held_out_returns_every_window_and_feature_family() -> None:
    rows = [
        _row("a", 0.94, 1.0),
        _row("a", 1.04, 2.0),
        _row("b", 0.96, 3.0),
        _row("b", 1.02, 4.0),
        _row("c", 0.98, 5.0),
        _row("c", 1.01, 6.0),
    ]
    results = evaluate_held_out(rows)
    expected = {"global_mean", "timing_bucket", *FEATURE_SETS}
    assert set(results) == expected
    assert all(len(folds) == 3 for folds in results.values())
    summary = summarize_results(results)
    assert set(summary) == expected
    assert "weighted_mae_delta_vs_timing" in summary["all"]
