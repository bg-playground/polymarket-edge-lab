from decimal import Decimal

from polymarket_edge_lab.analysis.timing_robustness import (
    WindowMetric,
    classify,
    cumulative,
    equal_window_mean,
    leave_one_out,
    weighted_cost,
)


def row(
    name: str,
    cost: str | None,
    *,
    qty: str = "600",
    complete: bool = True,
    start: int = 0,
) -> WindowMetric:
    return WindowMetric(
        window_id=name,
        start_epoch=start,
        end_epoch=start + 21600,
        complete=complete,
        paired_shares=Decimal(qty),
        weighted_pair_cost=Decimal(cost) if cost is not None else None,
        below_one_ratio=None,
    )


def test_weighted_and_equal_window_means_differ() -> None:
    rows = [row("a", "0.90", qty="500"), row("b", "1.10", qty="1500")]
    assert weighted_cost(rows) == Decimal("1.05")
    assert equal_window_mean(rows) == Decimal("1.00")


def test_classification_rules() -> None:
    replicated = [row(str(i), "0.98", start=i * 30000) for i in range(5)]
    assert classify(replicated) == "replicated"

    mixed = [
        row("a", "0.90"),
        row("b", "0.90"),
        row("c", "1.09"),
        row("d", "1.09"),
    ]
    assert classify(mixed) == "mixed"

    not_replicated = [row(str(i), "1.01") for i in range(4)]
    assert classify(not_replicated) == "not_replicated"

    assert classify([row("a", "0.9"), row("b", "0.9"), row("c", "0.9")]) == (
        "insufficient_data"
    )
    undersized = [row(str(i), "0.9", qty="499") for i in range(5)]
    assert classify(undersized) == "insufficient_data"
    incomplete = [row(str(i), "0.98") for i in range(4)] + [
        row("x", "0.98", complete=False)
    ]
    assert classify(incomplete) == "insufficient_data"


def test_leave_one_out_and_cumulative_are_chronological() -> None:
    rows = [row("late", "0.99", start=20), row("early", "0.97", start=10)]
    loo = leave_one_out(rows)
    assert loo[0]["omitted_window"] == "early"
    assert loo[0]["pooled_pair_cost"] == Decimal("0.99")
    cumulative_rows = cumulative(rows)
    assert cumulative_rows[0]["through_window"] == "early"
    assert cumulative_rows[0]["pooled_pair_cost"] == Decimal("0.97")
    assert cumulative_rows[1]["pooled_pair_cost"] == Decimal("0.98")


def test_decimal_precision_is_preserved() -> None:
    rows = [row("a", "0.984300000000000001"), row("b", "0.984300000000000003")]
    assert weighted_cost(rows) == Decimal("0.984300000000000002")
