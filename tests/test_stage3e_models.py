from __future__ import annotations

from typing import Any

from polymarket_edge_lab.analysis.stage3e_models import (
    evaluate_nonlinear_held_out,
    summarize_nonlinear_results,
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


def test_nonlinear_evaluation_preserves_complete_window_holdouts() -> None:
    rows = []
    for window in ("a", "b", "c"):
        rows.extend(_row(window, index) for index in range(220))

    results = evaluate_nonlinear_held_out(rows)

    assert set(results) == {
        "tree_timing_inventory",
        "hgb_timing_inventory",
        "hgb_inventory",
        "hgb_all",
    }
    for folds in results.values():
        assert [fold["held_out_window"] for fold in folds] == ["a", "b", "c"]
        assert all(fold["row_count"] == 220 for fold in folds)


def test_advancement_gate_requires_mean_and_day_level_wins() -> None:
    hurdle_folds = [
        {"held_out_window": str(index), "weighted_mae": 0.20, "brier": 0.24} for index in range(7)
    ]
    winning_folds = []
    for index in range(7):
        winning = index < 4
        winning_folds.append(
            {
                "held_out_window": str(index),
                "weighted_mae": 0.19 if winning else 0.201,
                "unweighted_mae": 0.19,
                "brier": 0.23 if winning else 0.241,
                "log_loss": 0.60,
            }
        )
    results = {
        "hgb_timing_inventory": winning_folds,
        "tree_timing_inventory": winning_folds,
        "hgb_inventory": winning_folds,
        "hgb_all": winning_folds,
    }

    summary = summarize_nonlinear_results(results, hurdle_folds)

    assert summary["hgb_timing_inventory"]["mae_day_wins_vs_hurdle"] == 4
    assert summary["hgb_timing_inventory"]["brier_day_wins_vs_hurdle"] == 4
    assert summary["hgb_timing_inventory"]["advancement_gate_passed"] is True
