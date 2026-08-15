from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from polymarket_edge_lab.shadow.evaluation import load_frozen_evaluation_start
from polymarket_edge_lab.shadow.scorer import MODEL_NAMES
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

REPORT_SCHEMA_VERSION = "m4a-prospective-report-v1"
REPORTABLE_DAY_MIN_BOUND_ROWS = 500
MIN_BOUND_ROWS = 20_000
MIN_REPORTABLE_DAYS = 10
MIN_ELAPSED_DAYS = 14
MAX_ELAPSED_DAYS = 28
CALIBRATION_BINS = 10


@dataclass(frozen=True)
class ModelMetrics:
    weighted_mae: float | None
    weighted_brier: float | None
    paired_share_weight: float
    row_count: int


@dataclass(frozen=True)
class ProspectiveReport:
    schema_version: str
    run_id: str
    evaluation_started_at: str
    generated_at: str
    elapsed_calendar_days: int
    total_pair_rows: int
    prospectively_bound_rows: int
    unbound_rows: int
    bound_coverage_rate: float | None
    bound_paired_share_weight: float
    reportable_days: list[str]
    reportable_day_count: int
    horizon_minimums_reached: bool
    horizon_day_28_exhausted: bool
    model_metrics: dict[str, ModelMetrics]
    calibration: dict[str, list[dict[str, float | int | None]]]
    freshness: dict[str, float | None]
    replay_audit_status: str


def _payload(record: dict[str, object], event_type: str) -> dict[str, object]:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"{event_type} payload must be an object")
    return payload


def _weighted_mean(values: list[tuple[float, float]]) -> float | None:
    weight = sum(item[1] for item in values)
    if weight <= 0:
        return None
    return sum(value * item_weight for value, item_weight in values) / weight


def _utc_date(value: object) -> date:
    return datetime.fromisoformat(str(value)).astimezone(UTC).date()


def _elapsed_days(started_at: datetime, generated_at: datetime) -> int:
    return (generated_at.astimezone(UTC).date() - started_at.astimezone(UTC).date()).days + 1


def build_prospective_report(
    store: AppendOnlyEventStore,
    *,
    generated_at: datetime,
) -> ProspectiveReport:
    start = load_frozen_evaluation_start(store)
    start_sequence = int(str(start["sequence"]))
    started_at = datetime.fromisoformat(str(start["created_at"])).astimezone(UTC)
    run_id = str(start["run_id"])
    records = [
        record
        for record in store.iter_records()
        if int(str(record["sequence"])) > start_sequence and str(record["run_id"]) == run_id
    ]

    predictions = {
        str(record["event_id"]): record
        for record in records
        if record.get("event_type") == "prediction"
    }
    outcomes: dict[str, dict[str, object]] = {}
    bindings: dict[str, dict[str, object]] = {}
    pairs: dict[str, dict[str, object]] = {}
    for record in records:
        event_type = str(record.get("event_type") or "")
        payload = record.get("payload")
        if event_type == "pair_formation":
            pairs[str(record["event_id"])] = record
        if not isinstance(payload, dict):
            continue
        pair_id = payload.get("pair_formation_event_id")
        if pair_id is None:
            continue
        if event_type == "outcome_label":
            outcomes[str(pair_id)] = record
        elif event_type == "score_binding":
            bindings[str(pair_id)] = record

    bound_rows: list[tuple[dict[str, object], dict[str, object], dict[str, object]]] = []
    unbound = 0
    day_counts: dict[date, int] = defaultdict(int)
    for pair_id, pair in pairs.items():
        binding = bindings.get(pair_id)
        outcome = outcomes.get(pair_id)
        if binding is None or outcome is None:
            continue
        binding_payload = _payload(binding, "score_binding")
        if binding_payload.get("status") != "bound_strictly_prior_score":
            unbound += 1
            continue
        prediction_id = binding_payload.get("prediction_event_id")
        prediction = predictions.get(str(prediction_id)) if prediction_id is not None else None
        if prediction is None:
            raise ValueError("bound score_binding references missing prediction")
        prediction_payload = _payload(prediction, "prediction")
        if prediction_payload.get("advancement_eligible_candidate") is not True:
            raise ValueError("bound prediction is not advancement eligible")
        if prediction_payload.get("event_conditioned_reconstruction") is not False:
            raise ValueError("event-conditioned prediction entered prospective report")
        outcome_payload = _payload(outcome, "outcome_label")
        formed_at = outcome_payload["formed_at_source_timestamp"]
        formed_dt = datetime.fromisoformat(str(formed_at)).astimezone(UTC)
        if not 12 <= formed_dt.hour < 18:
            continue
        bound_rows.append((prediction_payload, outcome_payload, pair))
        day_counts[formed_dt.date()] += 1

    model_metrics: dict[str, ModelMetrics] = {}
    calibration: dict[str, list[dict[str, float | int | None]]] = {}
    for name in MODEL_NAMES:
        absolute_errors: list[tuple[float, float]] = []
        brier_errors: list[tuple[float, float]] = []
        bins: list[list[tuple[float, float, float]]] = [[] for _ in range(CALIBRATION_BINS)]
        for prediction_payload, outcome_payload, _pair in bound_rows:
            outputs = prediction_payload.get("model_outputs")
            if not isinstance(outputs, dict):
                raise ValueError("prediction model_outputs must be an object")
            output = outputs.get(name)
            if not isinstance(output, dict):
                raise ValueError(f"prediction output missing for {name}")
            pair_cost = float(str(outcome_payload["pair_cost"]))
            favorable = 1.0 if outcome_payload["favorable"] is True else 0.0
            weight = float(str(outcome_payload["paired_shares"]))
            predicted_cost = float(str(output["predicted_pair_cost"]))
            probability = float(str(output["favorable_probability"]))
            absolute_errors.append((abs(predicted_cost - pair_cost), weight))
            brier_errors.append(((probability - favorable) ** 2, weight))
            index = min(CALIBRATION_BINS - 1, max(0, int(probability * CALIBRATION_BINS)))
            bins[index].append((probability, favorable, weight))
        total_weight = sum(weight for _value, weight in absolute_errors)
        model_metrics[name] = ModelMetrics(
            weighted_mae=_weighted_mean(absolute_errors),
            weighted_brier=_weighted_mean(brier_errors),
            paired_share_weight=total_weight,
            row_count=len(absolute_errors),
        )
        calibration[name] = [
            {
                "bin_index": index,
                "row_count": len(items),
                "paired_share_weight": sum(item[2] for item in items),
                "weighted_mean_probability": _weighted_mean([(item[0], item[2]) for item in items]),
                "weighted_favorable_rate": _weighted_mean([(item[1], item[2]) for item in items]),
            }
            for index, items in enumerate(bins)
        ]

    freshness_pairs: dict[str, list[tuple[float, float]]] = {
        "btc_age_seconds": [],
        "target_source_age_seconds": [],
    }
    for prediction_payload, outcome_payload, _pair in bound_rows:
        weight = float(str(outcome_payload["paired_shares"]))
        freshness = prediction_payload.get("input_freshness")
        if not isinstance(freshness, dict):
            continue
        for key in freshness_pairs:
            value = freshness.get(key)
            if value is not None:
                freshness_pairs[key].append((float(str(value)), weight))
    freshness = {key: _weighted_mean(values) for key, values in freshness_pairs.items()}

    reportable_days = sorted(
        day.isoformat() for day, count in day_counts.items() if count >= REPORTABLE_DAY_MIN_BOUND_ROWS
    )
    elapsed = _elapsed_days(started_at, generated_at)
    bound_count = len(bound_rows)
    coverage_denominator = bound_count + unbound
    coverage = None if coverage_denominator == 0 else bound_count / coverage_denominator
    bound_weight = sum(
        float(str(outcome_payload["paired_shares"]))
        for _prediction_payload, outcome_payload, _pair in bound_rows
    )
    replay_records = [record for record in records if record.get("event_type") == "replay_audit"]
    replay_status = "not_recorded"
    if replay_records:
        replay_payload = _payload(replay_records[-1], "replay_audit")
        replay_status = str(replay_payload.get("status") or "unknown")

    minimums = (
        elapsed >= MIN_ELAPSED_DAYS
        and len(reportable_days) >= MIN_REPORTABLE_DAYS
        and bound_count >= MIN_BOUND_ROWS
    )
    return ProspectiveReport(
        schema_version=REPORT_SCHEMA_VERSION,
        run_id=run_id,
        evaluation_started_at=started_at.isoformat(),
        generated_at=generated_at.astimezone(UTC).isoformat(),
        elapsed_calendar_days=elapsed,
        total_pair_rows=len(pairs),
        prospectively_bound_rows=bound_count,
        unbound_rows=unbound,
        bound_coverage_rate=coverage,
        bound_paired_share_weight=bound_weight,
        reportable_days=reportable_days,
        reportable_day_count=len(reportable_days),
        horizon_minimums_reached=minimums,
        horizon_day_28_exhausted=elapsed >= MAX_ELAPSED_DAYS and not minimums,
        model_metrics=model_metrics,
        calibration=calibration,
        freshness=freshness,
        replay_audit_status=replay_status,
    )


def write_report_json(report: ProspectiveReport, path: Path) -> None:
    path.write_text(json_dumps(report) + "\n", encoding="utf-8")


def json_dumps(report: ProspectiveReport) -> str:
    import json

    return json.dumps(asdict(report), indent=2, sort_keys=True)
