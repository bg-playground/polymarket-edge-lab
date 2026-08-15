from __future__ import annotations

from typing import Any

from polymarket_edge_lab.analysis.stage3g_models import advancement_gate


def _fold(window: str, mae: float, brier: float) -> dict[str, Any]:
    return {
        "held_out_window": window,
        "row_count": 100,
        "paired_share_weight": 100.0,
        "weighted_mae": mae,
        "unweighted_mae": mae,
        "weighted_bias": 0.0,
        "brier": brier,
        "log_loss": 0.6,
    }


def test_stage3g_gate_requires_external_day_wins_and_leakage_audit() -> None:
    windows = [str(index) for index in range(7)]
    primary = [_fold(window, 0.18, 0.21) for window in windows]
    hgb_base = [_fold(window, 0.20, 0.23) for window in windows]
    linear_base = [_fold(window, 0.21, 0.24) for window in windows]
    external = {
        "hgb_all_pre_event": primary,
        "hgb_timing_inventory": hgb_base,
        "linear_timing_inventory": linear_base,
        "hgb_timing_inventory_btc60": primary,
    }

    passed = advancement_gate(external, leakage_passed=True)
    failed = advancement_gate(external, leakage_passed=False)

    assert passed["passed"] is True
    assert passed["mae_day_wins"] == 7
    assert passed["brier_day_wins"] == 7
    assert failed["passed"] is False
    assert failed["checks"]["leakage_audit_passed"] is False
