from __future__ import annotations

from typing import Any

from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from polymarket_edge_lab.analysis.stage3d_models import (
    BTC_FEATURES,
    INVENTORY_FEATURES,
    TIMING_FEATURES,
)

TIMING_INVENTORY_FEATURES = TIMING_FEATURES + INVENTORY_FEATURES
ALL_USABLE_FEATURES = TIMING_FEATURES + INVENTORY_FEATURES + BTC_FEATURES

NONLINEAR_FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "tree_timing_inventory": TIMING_INVENTORY_FEATURES,
    "hgb_timing_inventory": TIMING_INVENTORY_FEATURES,
    "hgb_inventory": INVENTORY_FEATURES,
    "hgb_all": ALL_USABLE_FEATURES,
}


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
    from math import log

    labels = [bool(row["favorable"]) for row in rows]
    weights = _weights(rows)
    total = sum(weights)
    eps = 1e-12
    brier_terms: list[float] = []
    loss_terms: list[float] = []
    for label, probability, weight in zip(labels, probabilities, weights, strict=True):
        target = float(label)
        bounded = min(1.0 - eps, max(eps, probability))
        brier_terms.append(weight * (bounded - target) ** 2)
        positive_loss = target * log(bounded)
        negative_loss = (1.0 - target) * log(1.0 - bounded)
        loss_terms.append(weight * -(positive_loss + negative_loss))
    return sum(brier_terms) / total, sum(loss_terms) / total


def _tree_predictions(
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
            (
                "model",
                DecisionTreeRegressor(
                    max_depth=3,
                    min_samples_leaf=100,
                    random_state=0,
                ),
            ),
        ]
    )
    regression.fit(x_train, y_cost, model__sample_weight=weights)
    cost_predictions = [float(value) for value in regression.predict(x_test)]

    classification = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                DecisionTreeClassifier(
                    max_depth=3,
                    min_samples_leaf=100,
                    random_state=0,
                ),
            ),
        ]
    )
    classification.fit(x_train, y_binary, model__sample_weight=weights)
    probabilities = [float(value) for value in classification.predict_proba(x_test)[:, 1]]
    return cost_predictions, probabilities


def _hgb_predictions(
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
            (
                "model",
                HistGradientBoostingRegressor(
                    learning_rate=0.05,
                    max_depth=3,
                    max_iter=100,
                    min_samples_leaf=100,
                    l2_regularization=1.0,
                    random_state=0,
                ),
            ),
        ]
    )
    regression.fit(x_train, y_cost, model__sample_weight=weights)
    cost_predictions = [float(value) for value in regression.predict(x_test)]

    classification = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                HistGradientBoostingClassifier(
                    learning_rate=0.05,
                    max_depth=3,
                    max_iter=100,
                    min_samples_leaf=100,
                    l2_regularization=1.0,
                    random_state=0,
                ),
            ),
        ]
    )
    classification.fit(x_train, y_binary, model__sample_weight=weights)
    probabilities = [float(value) for value in classification.predict_proba(x_test)[:, 1]]
    return cost_predictions, probabilities


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


def evaluate_nonlinear_held_out(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    windows = sorted({str(row["window_id"]) for row in rows})
    results: dict[str, list[dict[str, Any]]] = {
        name: [] for name in NONLINEAR_FEATURE_SETS
    }
    for held_out in windows:
        train = [row for row in rows if str(row["window_id"]) != held_out]
        test = [row for row in rows if str(row["window_id"]) == held_out]
        for name, features in NONLINEAR_FEATURE_SETS.items():
            if name.startswith("tree_"):
                costs, probabilities = _tree_predictions(train, test, features)
            else:
                costs, probabilities = _hgb_predictions(train, test, features)
            results[name].append(_fold_payload(held_out, test, costs, probabilities))
    return results


def summarize_nonlinear_results(
    results: dict[str, list[dict[str, Any]]],
    hurdle_folds: list[dict[str, Any]],
) -> dict[str, dict[str, float | int | bool]]:
    hurdle_by_window = {str(fold["held_out_window"]): fold for fold in hurdle_folds}
    hurdle_mae = sum(float(fold["weighted_mae"]) for fold in hurdle_folds) / len(hurdle_folds)
    hurdle_brier = sum(float(fold["brier"]) for fold in hurdle_folds) / len(hurdle_folds)
    summary: dict[str, dict[str, float | int | bool]] = {}
    for name, folds in results.items():
        weighted_mae = sum(float(fold["weighted_mae"]) for fold in folds) / len(folds)
        unweighted_mae = sum(float(fold["unweighted_mae"]) for fold in folds) / len(folds)
        brier = sum(float(fold["brier"]) for fold in folds) / len(folds)
        log_loss = sum(float(fold["log_loss"]) for fold in folds) / len(folds)
        mae_day_wins = 0
        brier_day_wins = 0
        for fold in folds:
            window = str(fold["held_out_window"])
            hurdle = hurdle_by_window[window]
            if float(fold["weighted_mae"]) < float(hurdle["weighted_mae"]):
                mae_day_wins += 1
            if float(fold["brier"]) < float(hurdle["brier"]):
                brier_day_wins += 1
        summary[name] = {
            "weighted_mae": weighted_mae,
            "unweighted_mae": unweighted_mae,
            "brier": brier,
            "log_loss": log_loss,
            "weighted_mae_delta_vs_hurdle": weighted_mae - hurdle_mae,
            "brier_delta_vs_hurdle": brier - hurdle_brier,
            "mae_day_wins_vs_hurdle": mae_day_wins,
            "brier_day_wins_vs_hurdle": brier_day_wins,
        }

    primary = summary["hgb_timing_inventory"]
    primary["advancement_gate_passed"] = bool(
        float(primary["weighted_mae_delta_vs_hurdle"]) < 0.0
        and float(primary["brier_delta_vs_hurdle"]) < 0.0
        and int(primary["mae_day_wins_vs_hurdle"]) >= 4
        and int(primary["brier_day_wins_vs_hurdle"]) >= 4
    )
    return summary
