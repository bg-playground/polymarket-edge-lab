from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import joblib
import pytest
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.pipeline import Pipeline

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.shadow.evaluation import (
    FROZEN_TARGET_ACCOUNT,
    FrozenEvaluationConfig,
    start_frozen_evaluation,
    verify_frozen_evaluation,
)
from polymarket_edge_lab.shadow.events import EventEnvelope, EventType
from polymarket_edge_lab.shadow.reporting import build_prospective_report
from polymarket_edge_lab.shadow.scorer import MODEL_NAMES
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

RUN_ID = "m4a-frozen-20260816"
REPO_COMMIT = "1" * 40
START = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
MARKET = "0x" + "2" * 64


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    rows: list[dict[str, object]] = []
    for name in MODEL_NAMES:
        model_dir = root / name
        model_dir.mkdir(parents=True)
        width = len(MODEL_FEATURES[name])
        matrix = [[0.0] * width, [1.0] * width]
        regressor = Pipeline([("model", DummyRegressor(strategy="mean"))])
        classifier = Pipeline([("model", DummyClassifier(strategy="prior"))])
        regressor.fit(matrix, [0.9, 1.0])
        classifier.fit(matrix, [0, 1])
        regressor_path = model_dir / "regressor.joblib"
        classifier_path = model_dir / "classifier.joblib"
        joblib.dump(regressor, regressor_path)
        joblib.dump(classifier, classifier_path)
        rows.append(
            {
                "model_name": name,
                "features": list(MODEL_FEATURES[name]),
                "regressor_sha256": _sha256(regressor_path),
                "classifier_sha256": _sha256(classifier_path),
                "preprocessing_fingerprint": "a" * 64,
                "training_row_count": 100,
                "training_paired_share_weight": 123.0,
                "source_commit": "stage3g-commit",
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "m4a-model-manifest-v1",
                "source_commit": "stage3g-commit",
                "models": rows,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def _config(artifacts: Path) -> FrozenEvaluationConfig:
    return FrozenEvaluationConfig(
        run_id=RUN_ID,
        repository_commit=REPO_COMMIT,
        artifact_dir=artifacts,
    )


def _append(
    store: AppendOnlyEventStore,
    event_type: EventType,
    created_at: datetime,
    payload: dict[str, object],
) -> str:
    sequence = store.next_sequence()
    event_id = f"{RUN_ID}:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type=event_type,
            event_id=event_id,
            run_id=RUN_ID,
            sequence=sequence,
            created_at=created_at,
            payload=payload,
        )
    )
    return event_id


def _outputs(cost: float, probability: float) -> dict[str, object]:
    return {
        name: {
            "predicted_pair_cost": cost,
            "favorable_probability": probability,
        }
        for name in MODEL_NAMES
    }


def _append_bound_pair(
    store: AppendOnlyEventStore,
    *,
    index: int,
    pair_cost: float,
    favorable: bool,
    shares: float,
    predicted_cost: float,
    probability: float,
) -> None:
    at = START + timedelta(minutes=10, seconds=index)
    prediction_id = _append(
        store,
        "prediction",
        at - timedelta(seconds=1),
        {
            "market_id": MARKET,
            "model_outputs": _outputs(predicted_cost, probability),
            "advancement_eligible_candidate": True,
            "event_conditioned_reconstruction": False,
            "input_freshness": {
                "btc_age_seconds": 30,
                "target_source_age_seconds": 1,
            },
        },
    )
    pair_id = _append(
        store,
        "pair_formation",
        at,
        {
            "market_id": MARKET,
            "pair_cost": str(pair_cost),
            "paired_shares": str(shares),
        },
    )
    outcome_id = _append(
        store,
        "outcome_label",
        at,
        {
            "pair_formation_event_id": pair_id,
            "market_id": MARKET,
            "pair_cost": str(pair_cost),
            "favorable": favorable,
            "paired_shares": str(shares),
            "formed_at_source_timestamp": at.isoformat(),
        },
    )
    _append(
        store,
        "score_binding",
        at,
        {
            "pair_formation_event_id": pair_id,
            "outcome_label_event_id": outcome_id,
            "market_id": MARKET,
            "status": "bound_strictly_prior_score",
            "prediction_event_id": prediction_id,
        },
    )


def test_frozen_evaluation_start_is_sequence_zero_and_restart_verifies(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    config = _config(artifacts)

    event_id = start_frozen_evaluation(store=store, config=config, started_at=START)

    assert event_id == f"{RUN_ID}:0"
    record = list(store.iter_records())[0]
    assert record["event_type"] == "evaluation_run_start"
    payload = record["payload"]
    assert isinstance(payload, dict)
    assert payload["frozen_evaluation"] is True
    assert payload["target_account"] == FROZEN_TARGET_ACCOUNT
    verify_frozen_evaluation(store=store, config=config)


def test_frozen_evaluation_rejects_dirty_log_and_artifact_drift(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    dirty_store = AppendOnlyEventStore(tmp_path / "dirty.ndjson")
    _append(dirty_store, "source_health", START, {"source": "test", "status": "ok"})
    with pytest.raises(ValueError, match="empty event log"):
        start_frozen_evaluation(store=dirty_store, config=_config(artifacts), started_at=START)

    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    config = _config(artifacts)
    start_frozen_evaluation(store=store, config=config, started_at=START)
    path = artifacts / "hgb_all_pre_event" / "regressor.joblib"
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        verify_frozen_evaluation(store=store, config=config)


def test_frozen_evaluation_rejects_cadence_drift(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    with pytest.raises(ValueError, match="target poll interval"):
        start_frozen_evaluation(
            store=store,
            config=FrozenEvaluationConfig(
                run_id=RUN_ID,
                repository_commit=REPO_COMMIT,
                artifact_dir=artifacts,
                target_poll_interval_seconds=2.0,
            ),
            started_at=START,
        )


def test_report_uses_only_bound_advancement_eligible_rows(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    start_frozen_evaluation(store=store, config=_config(artifacts), started_at=START)
    _append_bound_pair(
        store,
        index=1,
        pair_cost=0.90,
        favorable=True,
        shares=2.0,
        predicted_cost=0.95,
        probability=0.80,
    )
    _append_bound_pair(
        store,
        index=2,
        pair_cost=1.10,
        favorable=False,
        shares=1.0,
        predicted_cost=1.00,
        probability=0.30,
    )
    at = START + timedelta(minutes=11)
    pair_id = _append(
        store,
        "pair_formation",
        at,
        {"market_id": MARKET, "pair_cost": "0.99", "paired_shares": "1"},
    )
    outcome_id = _append(
        store,
        "outcome_label",
        at,
        {
            "pair_formation_event_id": pair_id,
            "market_id": MARKET,
            "pair_cost": "0.99",
            "favorable": True,
            "paired_shares": "1",
            "formed_at_source_timestamp": at.isoformat(),
        },
    )
    _append(
        store,
        "score_binding",
        at,
        {
            "pair_formation_event_id": pair_id,
            "outcome_label_event_id": outcome_id,
            "market_id": MARKET,
            "status": "unbound_no_strictly_prior_score",
            "prediction_event_id": None,
        },
    )

    report = build_prospective_report(store, generated_at=START + timedelta(days=13))

    assert report.total_pair_rows == 3
    assert report.prospectively_bound_rows == 2
    assert report.unbound_rows == 1
    assert report.bound_coverage_rate == pytest.approx(2 / 3)
    assert report.bound_paired_share_weight == pytest.approx(3.0)
    assert report.elapsed_calendar_days == 14
    assert report.reportable_day_count == 0
    assert report.horizon_minimums_reached is False
    assert report.replay_audit_status == "not_recorded"
    primary = report.model_metrics["hgb_all_pre_event"]
    assert primary.row_count == 2
    assert primary.paired_share_weight == pytest.approx(3.0)
    assert primary.weighted_mae == pytest.approx((0.05 * 2 + 0.10) / 3)
    assert primary.weighted_brier == pytest.approx((0.04 * 2 + 0.09) / 3)
    assert report.freshness["btc_age_seconds"] == pytest.approx(30.0)
    assert report.freshness["target_source_age_seconds"] == pytest.approx(1.0)
