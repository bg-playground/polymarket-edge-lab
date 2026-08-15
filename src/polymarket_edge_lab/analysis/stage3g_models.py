from __future__ import annotations

from typing import Any

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from polymarket_edge_lab.analysis.stage3d_models import BTC_FEATURES, INVENTORY_FEATURES
from polymarket_edge_lab.analysis.stage3e_models import _fold_payload, _hgb_predictions

PRE_TIMING_FEATURES = ("elapsed_seconds", "seconds_remaining")
PRE_INVENTORY_FEATURES = INVENTORY_FEATURES
PRE_BTC_FEATURES = BTC_FEATURES
PRE_TIMING_INVENTORY = PRE_TIMING_FEATURES + PRE_INVENTORY_FEATURES
PRE_BTC60 = PRE_TIMING_INVENTORY + ("btc_return_60s",)
PRE_ALL = PRE_TIMING_INVENTORY + PRE_BTC_FEATURES

MODEL_FEATURES: dict[str, tuple[str, ...]] = {
    "linear_timing_inventory": PRE_TIMING_INVENTORY,
    "hgb_timing_inventory": PRE_TIMING_INVENTORY,
    "hgb_timing_inventory_btc60": PRE_BTC60,
    "hgb_all_pre_event": PRE_ALL,
}


def _matrix(rows: list[dict[str, Any]], features: tuple[str, ...]) -> list[list[float]]:
    return [
        [
            float(row[feature]) if row.get(feature) is not None else float("nan")
            for feature in features
        ]
        for row in rows
    ]


def _weights(rows: list[dict[str, Any]]) -> list[float]:
    return [float(row["paired_shares"]) for row in rows]


def _linear_predictions(
    train: list[dict[str, Any]], test: list[dict[str, Any]], features: tuple[str, ...]
) -> tuple[list[float], list[float]]:
    x_train = _matrix(train, features)
    x_test = _matrix(test, features)
    weights = _weights(train)
    regression = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=1.0)),
        ]
    )
    y_cost = [float(row["pair_cost"]) for row in train]
    regression.fit(x_train, y_cost, model__sample_weight=weights)
    classifier = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=1.0, max_iter=1000, random_state=0)),
        ]
    )
    classifier.fit(
        x_train,
        [int(bool(row["favorable"])) for row in train],
        model__sample_weight=weights,
    )
    costs = [float(value) for value in regression.predict(x_test)]
    probabilities = [float(value) for value in classifier.predict_proba(x_test)[:, 1]]
    return costs, probabilities


def evaluate_discovery(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    windows = sorted({str(row["window_id"]) for row in rows})
    results: dict[str, list[dict[str, Any]]] = {name: [] for name in MODEL_FEATURES}
    for held_out in windows:
        train = [row for row in rows if str(row["window_id"]) != held_out]
        test = [row for row in rows if str(row["window_id"]) == held_out]
        for name, features in MODEL_FEATURES.items():
            if name.startswith("linear_"):
                costs, probabilities = _linear_predictions(train, test, features)
            else:
                costs, probabilities = _hgb_predictions(train, test, features)
            results[name].append(_fold_payload(held_out, test, costs, probabilities))
    return results


def evaluate_external(
    discovery_rows: list[dict[str, Any]], external_rows: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    windows = sorted({str(row["window_id"]) for row in external_rows})
    results: dict[str, list[dict[str, Any]]] = {name: [] for name in MODEL_FEATURES}
    for name, features in MODEL_FEATURES.items():
        for window in windows:
            test = [row for row in external_rows if str(row["window_id"]) == window]
            if name.startswith("linear_"):
                costs, probabilities = _linear_predictions(discovery_rows, test, features)
            else:
                costs, probabilities = _hgb_predictions(discovery_rows, test, features)
            results[name].append(_fold_payload(window, test, costs, probabilities))
    return results


def _aggregate(folds: list[dict[str, Any]]) -> dict[str, float]:
    total_weight = sum(float(fold["paired_share_weight"]) for fold in folds)
    return {
        "weighted_mae": sum(
            float(fold["weighted_mae"]) * float(fold["paired_share_weight"]) for fold in folds
        )
        / total_weight,
        "brier": sum(
            float(fold["brier"]) * float(fold["paired_share_weight"]) for fold in folds
        )
        / total_weight,
    }


def advancement_gate(
    external: dict[str, list[dict[str, Any]]], *, leakage_passed: bool
) -> dict[str, Any]:
    primary = external["hgb_all_pre_event"]
    hgb_base = external["hgb_timing_inventory"]
    linear_base = external["linear_timing_inventory"]
    primary_agg = _aggregate(primary)
    hgb_agg = _aggregate(hgb_base)
    linear_agg = _aggregate(linear_base)
    mae_wins = sum(
        float(left["weighted_mae"]) < float(right["weighted_mae"])
        for left, right in zip(primary, hgb_base, strict=True)
    )
    brier_wins = sum(
        float(left["brier"]) < float(right["brier"])
        for left, right in zip(primary, hgb_base, strict=True)
    )
    enough_days = len(primary) == 7 and all(int(fold["row_count"]) > 0 for fold in primary)
    checks = {
        "mae_better_than_hgb_timing_inventory": (
            primary_agg["weighted_mae"] < hgb_agg["weighted_mae"]
        ),
        "brier_better_than_hgb_timing_inventory": primary_agg["brier"] < hgb_agg["brier"],
        "mae_wins_at_least_4_of_7": mae_wins >= 4,
        "brier_wins_at_least_4_of_7": brier_wins >= 4,
        "mae_better_than_linear_baseline": primary_agg["weighted_mae"]
        < linear_agg["weighted_mae"],
        "brier_better_than_linear_baseline": primary_agg["brier"] < linear_agg["brier"],
        "leakage_audit_passed": leakage_passed,
        "all_external_days_reportable": enough_days,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "mae_day_wins": mae_wins,
        "brier_day_wins": brier_wins,
        "aggregate": {
            "hgb_all_pre_event": primary_agg,
            "hgb_timing_inventory": hgb_agg,
            "linear_timing_inventory": linear_agg,
        },
    }
