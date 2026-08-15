from __future__ import annotations

from typing import Any

from polymarket_edge_lab.analysis.stage3f_forensics import (
    external_validation,
    held_out_btc_permutation_results,
)


def _row(window: str, index: int) -> dict[str, Any]:
    favorable = index % 2 == 0
    return {
        "window_id": window,
        "pair_cost": 0.95 if favorable else 1.05,
        "paired_shares": 1.0,
        "favorable": favorable,
        "lag_seconds": float(index % 150),
        "elapsed_seconds": float(index % 300),
        "seconds_remaining": float(300 - (index % 300)),
        "up_inventory": float(index % 11),
        "down_inventory": float(index % 13),
        "paired_inventory": float(index % 7),
        "residual_inventory": float(index % 5),
        "inventory_imbalance": float((index % 9) - 4),
        "seconds_since_last_up_fill": float(index % 20),
        "seconds_since_last_down_fill": float(index % 25),
        "fill_count_15s": float(index % 4),
        "fill_count_30s": float(index % 6),
        "fill_count_60s": float(index % 8),
        "fill_qty_15s": float(index % 5),
        "fill_qty_30s": float(index % 7),
        "fill_qty_60s": float(index % 9),
        "side_switches_60s": float(index % 3),
        "cumulative_paired_quantity": float(index),
        "same_second_fill_count": float(index % 2),
        "btc_return_60s": float((index % 7) - 3) / 1000.0,
        "btc_return_120s": float((index % 9) - 4) / 1000.0,
        "btc_absolute_return_60s": float(index % 4) / 1000.0,
        "btc_return_since_market_start": float((index % 11) - 5) / 1000.0,
        "btc_range_since_market_start": float(index % 6) / 1000.0,
    }


def test_btc_permutations_cover_each_feature_and_joint_group() -> None:
    rows = []
    for window in ("a", "b", "c"):
        rows.extend(_row(window, index) for index in range(220))

    results = held_out_btc_permutation_results(rows)

    assert len(results) == 3 * 6
    assert {result["permutation"] for result in results} == {
        "btc_return_60s",
        "btc_return_120s",
        "btc_absolute_return_60s",
        "btc_return_since_market_start",
        "btc_range_since_market_start",
        "btc_joint",
    }


def test_external_validation_scores_each_external_window() -> None:
    discovery = []
    for window in ("d1", "d2", "d3"):
        discovery.extend(_row(window, index) for index in range(220))
    external = []
    for window in ("e1", "e2"):
        external.extend(_row(window, index) for index in range(220))

    result = external_validation(discovery, external)

    assert set(result["folds"]) == {
        "transparent_timing_inventory",
        "hgb_timing_inventory",
        "hgb_all",
    }
    assert all(len(folds) == 2 for folds in result["folds"].values())
    assert set(result["gate"]) == {
        "aggregate_mae_better_than_hgb_timing_inventory",
        "aggregate_brier_better_than_hgb_timing_inventory",
        "mae_day_wins_at_least_4",
        "brier_day_wins_at_least_4",
        "aggregate_mae_better_than_transparent",
        "aggregate_brier_better_than_transparent",
    }
