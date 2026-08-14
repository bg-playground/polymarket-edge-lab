from decimal import Decimal

from polymarket_edge_lab.analysis.stage3b_baselines import (
    PanelRow,
    leave_one_window_out,
    mean_predictions,
    timing_predictions,
)


def _row(window: str, cost: str, lag: int, elapsed: int) -> PanelRow:
    return PanelRow(
        window_id=window,
        pair_cost=Decimal(cost),
        paired_shares=Decimal("10"),
        elapsed_seconds=elapsed,
        lag_seconds=lag,
        features={},
    )


def test_leave_one_window_out_never_trains_on_held_out_window() -> None:
    rows = [
        _row("a", "0.90", 80, 150),
        _row("b", "1.10", 10, 250),
        _row("c", "1.00", 80, 150),
    ]
    results = leave_one_window_out(rows, mean_predictions)
    by_window = {str(row["held_out_window"]): row for row in results}
    assert set(by_window) == {"a", "b", "c"}
    assert by_window["a"]["weighted_bias"] > 0
    assert by_window["b"]["weighted_bias"] < 0


def test_timing_predictions_use_training_bucket_then_global_fallback() -> None:
    train = [_row("a", "0.90", 80, 150), _row("a", "1.10", 10, 250)]
    test = [_row("b", "1.00", 80, 150), _row("b", "1.00", 200, 50)]
    predictions = timing_predictions(train, test)
    assert predictions[0] == Decimal("0.90")
    assert predictions[1] == Decimal("1.00")
