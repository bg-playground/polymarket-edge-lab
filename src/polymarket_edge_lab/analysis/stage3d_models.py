from __future__ import annotations

from dataclasses import dataclass
from math import log
from typing import Any

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TIMING_FEATURES = (
    "lag_seconds",
    "elapsed_seconds",
    "seconds_remaining",
)

# Primary inventory features intentionally exclude cumulative price/VWAP fields because those
# incorporate the pair-forming execution itself. They remain available in the panel for diagnostics.
INVENTORY_FEATURES = (
    "up_inventory",
    "down_inventory",
    "paired_inventory",
    "residual_inventory",
    "inventory_imbalance",
    "seconds_since_last_up_fill",
    "seconds_since_last_down_fill",
    "fill_count_15s",
    "fill_count_30s",
    "fill_count_60s",
    "fill_qty_15s",
    "fill_qty_30s",
    "fill_qty_60s",
    "side_switches_60s",
    "cumulative_paired_quantity",
    "same_second_fill_count",
)

BTC_FEATURES = (
    "btc_return_60s",
    "btc_return_120s",
    "btc_absolute_return_60s",
    "btc_return_since_market_start",
    "btc_range_since_market_start",
)

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "timing": TIMING_FEATURES,
    "inventory": INVENTORY_FEATURES,
    "btc": BTC_FEATURES,
    "timing_inventory": TIMING_FEATURES + INVENTORY_FEATURES,
    "timing_btc": TIMING_FEATURES + BTC_FEATURES,
    "inventory_btc": INVENTORY_FEATURES + BTC_FEATURES,
    "all": TIMING_FEATURES + INVENTORY_FEATURES + BTC_FEATURES,
}


@dataclass(frozen=True)
class FoldMetrics:
    held_out_window: str
    row_count: int
    paired_share_weight: float
    weighted_mae: float
    unweighted_mae: float
    weighted_bias: float
    brier: float
    log_loss: float


def _matrix(rows: list[dict[str, Any]], features: tuple[str, ...]) -> list[list[float]]:
    matrix: list[list[float]] = []
    for row in rows:
        values: list[float] = []
        for feature in features:
            value = row.get(feature)
            values.append(float(value) if value is not None else float("nan"))
        matrix.append(values)
    return matrix


def _weights(rows: list[dict[str, Any]]) -> list[float]:
    return [float(row["paired_shares"]) for row in rows]


def _regression_metrics(
    rows: list[dict[str, Any]], predictions: list[float]
) -> tuple[float, float, float]:
    actual = [float(row["pair_cost"]) for row in rows]
    weights = _weights(rows)
    total = sum(weights)
    errors = [pred - obs for pred, obs in zip(predictions, actual, strict=True)]
    weighted_mae = sum(w * abs(err) for w, err in zip(weights, errors, strict=True)) / total
    unweighted_mae = sum(abs(err) for err in errors) / len(errors)
    weighted_bias = sum(w * err for w, err in zip(weights, errors, strict=True)) / total
    return weighted_mae, unweighted_mae, weighted_bias


def _classification_metrics(
    rows: list[dict[str, Any]], probabilities: list[float]
) -> tuple[float, float]:
    labels = [bool(row["favorable"]) for row in rows]
    weights = _weights(rows)
    total = sum(weights)
    eps = 1e-12
    brier_terms = []
    loss_terms = []
    for label, probability, weight in zip(labels, probabilities, weights, strict=True):
        target = float(label)
        bounded = min(1.0 - eps, max(eps, probability))
        brier_terms.append(weight * (bounded - target) ** 2)
        loss_terms.append(
            weight * (-(target * log(bounded) + (1.0 - target) * log(1.0 - bounded)))
        )
    return sum(brier_terms) / total, sum(loss_terms) / total


def _fit_feature_models(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    features: tuple[str, ...],
) -> tuple[list[float], list[float]]:
    x_train = _matrix(train, features)
    x_test = _matrix(test, features)
    y_cost = [float(row["pair_cost"]) for row in train]
    y_binary = [int(bool(row["favorable"])) for row in train]
    weights = _weights(train)

    regression = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=1.0)),
        ]
    )
    regression.fit(x_train, y_cost, model__sample_weight=weights)
    cost_predictions = [float(value) for value in regression.predict(x_test)]

    classification = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=1.0, max_iter=2000)),
        ]
    )
    classification.fit(x_train, y_binary, model__sample_weight=weights)
    probabilities = [float(value) for value in classification.predict_proba(x_test)[:, 1]]
    return cost_predictions, probabilities


def _global_predictions(
    train: list[dict[str, Any]], test: list[dict[str, Any]]
) -> tuple[list[float], list[float]]:
    weights = _weights(train)
    total = sum(weights)
    mean_cost = sum(float(row["pair_cost"]) * weight for row, weight in zip(train, weights, strict=True)) / total
    favorable_rate = sum(
        float(bool(row["favorable"])) * weight for row, weight in zip(train, weights, strict=True)
    ) / total
    return [mean_cost] * len(test), [favorable_rate] * len(test)


def _timing_bucket(row: dict[str, Any]) -> tuple[str, str]:
    lag = row.get("lag_seconds")
    elapsed = row.get("elapsed_seconds")
    if lag is None:
        lag_key = "null"
    elif float(lag) <= 30:
        lag_key = "0-30"
    elif float(lag) <= 60:
        lag_key = "31-60"
    elif float(lag) <= 120:
        lag_key = "61-120"
    else:
        lag_key = ">120"
    if elapsed is None:
        time_key = "null"
    elif float(elapsed) < 100:
        time_key = "0-99"
    elif float(elapsed) < 200:
        time_key = "100-199"
    else:
        time_key = "200-299"
    return lag_key, time_key


def _timing_bucket_predictions(
    train: list[dict[str, Any]], test: list[dict[str, Any]]
) -> tuple[list[float], list[float]]:
    global_cost, global_prob = _global_predictions(train, test[:1])
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in train:
        grouped.setdefault(_timing_bucket(row), []).append(row)
    stats: dict[tuple[str, str], tuple[float, float]] = {}
    for key, rows in grouped.items():
        cost, probability = _global_predictions(rows, rows[:1])
        stats[key] = (cost[0], probability[0])
    costs: list[float] = []
    probabilities: list[float] = []
    for row in test:
        cost, probability = stats.get(_timing_bucket(row), (global_cost[0], global_prob[0]))
        costs.append(cost)
        probabilities.append(probability)
    return costs, probabilities


def evaluate_held_out(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Evaluate fixed feature families with one calendar window held out at a time."""
    windows = sorted({str(row["window_id"]) for row in rows})
    results: dict[str, list[dict[str, Any]]] = {"global_mean": [], "timing_bucket": []}
    for name in FEATURE_SETS:
        results[name] = []

    for held_out in windows:
        train = [row for row in rows if str(row["window_id"]) != held_out]
        test = [row for row in rows if str(row["window_id"]) == held_out]
        for name, predictor in (
            ("global_mean", _global_predictions),
            ("timing_bucket", _timing_bucket_predictions),
        ):
            costs, probabilities = predictor(train, test)
            results[name].append(_fold_payload(held_out, test, costs, probabilities))
        for name, features in FEATURE_SETS.items():
            costs, probabilities = _fit_feature_models(train, test, features)
            results[name].append(_fold_payload(held_out, test, costs, probabilities))
    return results


def _fold_payload(
    held_out: str,
    test: list[dict[str, Any]],
    costs: list[float],
    probabilities: list[float],
) -> dict[str, Any]:
    weighted_mae, unweighted_mae, weighted_bias = _regression_metrics(test, costs)
    brier, loss = _classification_metrics(test, probabilities)
    return {
        "held_out_window": held_out,
        "row_count": len(test),
        "paired_share_weight": sum(_weights(test)),
        "weighted_mae": weighted_mae,
        "unweighted_mae": unweighted_mae,
        "weighted_bias": weighted_bias,
        "brier": brier,
        "log_loss": loss,
    }


def summarize_results(results: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for name, folds in results.items():
        summary[name] = {
            metric: sum(float(fold[metric]) for fold in folds) / len(folds)
            for metric in ("weighted_mae", "unweighted_mae", "brier", "log_loss")
        }
    timing_mae = summary["timing"]["weighted_mae"]
    timing_brier = summary["timing"]["brier"]
    for name, metrics in summary.items():
        metrics["weighted_mae_delta_vs_timing"] = metrics["weighted_mae"] - timing_mae
        metrics["brier_delta_vs_timing"] = metrics["brier"] - timing_brier
    return summary
