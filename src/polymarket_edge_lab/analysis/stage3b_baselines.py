from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from math import log

ZERO = Decimal("0")


@dataclass(frozen=True)
class PanelRow:
    window_id: str
    pair_cost: Decimal
    paired_shares: Decimal
    elapsed_seconds: int | None
    lag_seconds: int | None
    features: dict[str, float | None]


def weighted_mean(rows: list[PanelRow]) -> Decimal | None:
    weight = sum((row.paired_shares for row in rows), start=ZERO)
    if weight == ZERO:
        return None
    return sum((row.pair_cost * row.paired_shares for row in rows), start=ZERO) / weight


def timing_bucket(row: PanelRow) -> tuple[str, str]:
    lag = row.lag_seconds
    elapsed = row.elapsed_seconds
    if lag is None:
        lag_key = "lag:null"
    elif lag <= 30:
        lag_key = "lag:0-30"
    elif lag <= 60:
        lag_key = "lag:31-60"
    elif lag <= 120:
        lag_key = "lag:61-120"
    else:
        lag_key = "lag:>120"
    if elapsed is None:
        time_key = "time:null"
    elif elapsed < 100:
        time_key = "time:0-99"
    elif elapsed < 200:
        time_key = "time:100-199"
    else:
        time_key = "time:200-299"
    return lag_key, time_key


def mean_predictions(train: list[PanelRow], test: list[PanelRow]) -> list[Decimal]:
    mean = weighted_mean(train)
    if mean is None:
        raise ValueError("training fold has zero paired-share weight")
    return [mean for _ in test]


def timing_predictions(train: list[PanelRow], test: list[PanelRow]) -> list[Decimal]:
    fallback = weighted_mean(train)
    if fallback is None:
        raise ValueError("training fold has zero paired-share weight")
    grouped: dict[tuple[str, str], list[PanelRow]] = {}
    for row in train:
        grouped.setdefault(timing_bucket(row), []).append(row)
    means = {key: weighted_mean(rows) for key, rows in grouped.items()}
    return [means.get(timing_bucket(row)) or fallback for row in test]


def regression_metrics(rows: list[PanelRow], predictions: list[Decimal]) -> dict[str, float]:
    if len(rows) != len(predictions) or not rows:
        raise ValueError("rows and predictions must be non-empty and equal length")
    weights = [float(row.paired_shares) for row in rows]
    errors = [float(pred - row.pair_cost) for row, pred in zip(rows, predictions, strict=True)]
    total_weight = sum(weights)
    weighted_mae = (
        sum(w * abs(error) for w, error in zip(weights, errors, strict=True)) / total_weight
    )
    unweighted_mae = sum(abs(error) for error in errors) / len(errors)
    weighted_pairs = zip(weights, errors, strict=True)
    weighted_bias = sum(w * error for w, error in weighted_pairs) / total_weight
    return {
        "weighted_mae": weighted_mae,
        "unweighted_mae": unweighted_mae,
        "weighted_bias": weighted_bias,
        "row_count": float(len(rows)),
        "paired_share_weight": total_weight,
    }


def leave_one_window_out(
    rows: list[PanelRow], predictor: Callable[[list[PanelRow], list[PanelRow]], list[Decimal]]
) -> list[dict[str, float | str]]:
    results: list[dict[str, float | str]] = []
    for window_id in sorted({row.window_id for row in rows}):
        train = [row for row in rows if row.window_id != window_id]
        test = [row for row in rows if row.window_id == window_id]
        if not train or not test:
            continue
        metrics = regression_metrics(test, predictor(train, test))
        results.append({"held_out_window": window_id, **metrics})
    return results


def brier_score(actual: list[bool], probabilities: list[float]) -> float:
    squared_errors = [
        (probability - float(label)) ** 2
        for label, probability in zip(actual, probabilities, strict=True)
    ]
    return sum(squared_errors) / len(actual)


def log_loss(actual: list[bool], probabilities: list[float]) -> float:
    eps = 1e-12
    values = []
    for y, p in zip(actual, probabilities, strict=True):
        bounded = min(1 - eps, max(eps, p))
        values.append(-(float(y) * log(bounded) + (1 - float(y)) * log(1 - bounded)))
    return sum(values) / len(values)
