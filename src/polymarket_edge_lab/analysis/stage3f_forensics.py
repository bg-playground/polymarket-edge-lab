from __future__ import annotations

from copy import deepcopy
from random import Random
from typing import Any

from polymarket_edge_lab.analysis.stage3d_models import (
    BTC_FEATURES,
    INVENTORY_FEATURES,
    TIMING_FEATURES,
    _fit_feature_models,
    _fold_payload,
)
from polymarket_edge_lab.analysis.stage3e_models import _hgb_predictions

TIMING_INVENTORY = TIMING_FEATURES + INVENTORY_FEATURES
ALL_FEATURES = TIMING_INVENTORY + BTC_FEATURES


def _mean(folds: list[dict[str, Any]], metric: str) -> float:
    return sum(float(fold[metric]) for fold in folds) / len(folds)


def _evaluate_hgb(
    rows: list[dict[str, Any]], features: tuple[str, ...]
) -> list[dict[str, Any]]:
    windows = sorted({str(row["window_id"]) for row in rows})
    folds: list[dict[str, Any]] = []
    for held_out in windows:
        train = [row for row in rows if str(row["window_id"]) != held_out]
        test = [row for row in rows if str(row["window_id"]) == held_out]
        costs, probabilities = _hgb_predictions(train, test, features)
        folds.append(_fold_payload(held_out, test, costs, probabilities))
    return folds


def discovery_ablation_results(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    feature_sets: dict[str, tuple[str, ...]] = {
        "timing_inventory": TIMING_INVENTORY,
        "timing_btc": TIMING_FEATURES + BTC_FEATURES,
        "inventory_btc": INVENTORY_FEATURES + BTC_FEATURES,
        "all": ALL_FEATURES,
    }
    for feature in BTC_FEATURES:
        feature_sets[f"timing_inventory_plus_{feature}"] = TIMING_INVENTORY + (feature,)
    return {name: _evaluate_hgb(rows, features) for name, features in feature_sets.items()}


def summarize_ablation_results(
    results: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, float]]:
    baseline = results["timing_inventory"]
    baseline_mae = _mean(baseline, "weighted_mae")
    baseline_brier = _mean(baseline, "brier")
    summary: dict[str, dict[str, float]] = {}
    for name, folds in results.items():
        summary[name] = {
            "weighted_mae": _mean(folds, "weighted_mae"),
            "brier": _mean(folds, "brier"),
            "weighted_mae_delta_vs_timing_inventory": _mean(folds, "weighted_mae")
            - baseline_mae,
            "brier_delta_vs_timing_inventory": _mean(folds, "brier") - baseline_brier,
        }
    return summary


def _permuted_rows(
    rows: list[dict[str, Any]], features: tuple[str, ...], seed: int
) -> list[dict[str, Any]]:
    copied = deepcopy(rows)
    order = list(range(len(rows)))
    Random(seed).shuffle(order)
    for target_index, source_index in enumerate(order):
        for feature in features:
            copied[target_index][feature] = rows[source_index].get(feature)
    return copied


def held_out_btc_permutation_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows = sorted({str(row["window_id"]) for row in rows})
    results: list[dict[str, Any]] = []
    for window_index, held_out in enumerate(windows):
        train = [row for row in rows if str(row["window_id"]) != held_out]
        test = [row for row in rows if str(row["window_id"]) == held_out]
        base_costs, base_probabilities = _hgb_predictions(train, test, ALL_FEATURES)
        base = _fold_payload(held_out, test, base_costs, base_probabilities)
        groups = [(feature, (feature,)) for feature in BTC_FEATURES]
        groups.append(("btc_joint", BTC_FEATURES))
        for feature_index, (name, features) in enumerate(groups):
            permuted = _permuted_rows(test, features, 1000 + window_index * 100 + feature_index)
            costs, probabilities = _hgb_predictions(train, permuted, ALL_FEATURES)
            metric = _fold_payload(held_out, test, costs, probabilities)
            results.append(
                {
                    "held_out_window": held_out,
                    "permutation": name,
                    "weighted_mae_delta": float(metric["weighted_mae"])
                    - float(base["weighted_mae"]),
                    "brier_delta": float(metric["brier"]) - float(base["brier"]),
                }
            )
    return results


def external_validation(
    discovery_rows: list[dict[str, Any]], external_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    windows = sorted({str(row["window_id"]) for row in external_rows})
    results: dict[str, list[dict[str, Any]]] = {
        "transparent_timing_inventory": [],
        "hgb_timing_inventory": [],
        "hgb_all": [],
    }
    for held_out in windows:
        test = [row for row in external_rows if str(row["window_id"]) == held_out]
        costs, probabilities = _fit_feature_models(discovery_rows, test, TIMING_INVENTORY)
        results["transparent_timing_inventory"].append(
            _fold_payload(held_out, test, costs, probabilities)
        )
        costs, probabilities = _hgb_predictions(discovery_rows, test, TIMING_INVENTORY)
        results["hgb_timing_inventory"].append(_fold_payload(held_out, test, costs, probabilities))
        costs, probabilities = _hgb_predictions(discovery_rows, test, ALL_FEATURES)
        results["hgb_all"].append(_fold_payload(held_out, test, costs, probabilities))

    hgb_all = results["hgb_all"]
    hgb_ti = results["hgb_timing_inventory"]
    transparent = results["transparent_timing_inventory"]
    mae_wins = sum(
        float(candidate["weighted_mae"]) < float(reference["weighted_mae"])
        for candidate, reference in zip(hgb_all, hgb_ti, strict=True)
    )
    brier_wins = sum(
        float(candidate["brier"]) < float(reference["brier"])
        for candidate, reference in zip(hgb_all, hgb_ti, strict=True)
    )
    gate = {
        "aggregate_mae_better_than_hgb_timing_inventory": _mean(hgb_all, "weighted_mae")
        < _mean(hgb_ti, "weighted_mae"),
        "aggregate_brier_better_than_hgb_timing_inventory": _mean(hgb_all, "brier")
        < _mean(hgb_ti, "brier"),
        "mae_day_wins_at_least_4": mae_wins >= 4,
        "brier_day_wins_at_least_4": brier_wins >= 4,
        "aggregate_mae_better_than_transparent": _mean(hgb_all, "weighted_mae")
        < _mean(transparent, "weighted_mae"),
        "aggregate_brier_better_than_transparent": _mean(hgb_all, "brier")
        < _mean(transparent, "brier"),
    }
    return {
        "folds": results,
        "summary": {
            name: {"weighted_mae": _mean(folds, "weighted_mae"), "brier": _mean(folds, "brier")}
            for name, folds in results.items()
        },
        "mae_day_wins_vs_hgb_timing_inventory": mae_wins,
        "brier_day_wins_vs_hgb_timing_inventory": brier_wins,
        "gate": gate,
        "external_confirmation_gate_passed": all(gate.values()),
    }
