from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import joblib
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.pipeline import Pipeline

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.shadow.binding import ProspectiveOutcomeBinder
from polymarket_edge_lab.shadow.bounded_replay import audit_bounded_shadow_replay
from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.feature_builder import LiveStage3GFeatureBuilder
from polymarket_edge_lab.shadow.scorer import MODEL_NAMES, LiveShadowScorer
from polymarket_edge_lab.shadow.state_processor import LiveStateProcessor
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

RUN_ID = "run-bounded-replay"
MARKET = "0x" + "9" * 64
START = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
START_EPOCH = int(START.timestamp())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    rows: list[dict[str, object]] = []
    for name in MODEL_NAMES:
        model_dir = root / name
        model_dir.mkdir(parents=True)
        regressor = Pipeline([("model", DummyRegressor(strategy="constant", constant=0.97))])
        classifier = Pipeline([("model", DummyClassifier(strategy="prior"))])
        width = len(MODEL_FEATURES[name])
        matrix = [[0.0] * width, [1.0] * width]
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
            }
        )
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": "m4a-model-manifest-v1", "models": rows}),
        encoding="utf-8",
    )
    return root


def _append(
    store: AppendOnlyEventStore,
    event_type: str,
    created_at: datetime,
    payload: dict[str, object],
) -> str:
    sequence = store.next_sequence()
    event_id = f"{RUN_ID}:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type=event_type,  # type: ignore[arg-type]
            event_id=event_id,
            run_id=RUN_ID,
            sequence=sequence,
            created_at=created_at,
            payload=payload,
        )
    )
    return event_id


def _seed_market_inputs(store: AppendOnlyEventStore) -> None:
    metadata = {
        "condition_id": MARKET,
        "gamma_market_id": "123",
        "slug": f"btc-updown-5m-{START_EPOCH}",
        "question": "Bitcoin Up or Down",
        "market_start_epoch": START_EPOCH,
        "market_end_epoch": START_EPOCH + 300,
        "up_token_id": "asset-up",
        "down_token_id": "asset-down",
        "active": True,
        "closed": False,
        "accepting_orders": True,
        "raw_observation_sha256": "a" * 64,
    }
    _append(
        store,
        "market_metadata",
        START,
        {
            "condition_id": MARKET,
            "eligible": True,
            "reason_code": "eligible",
            "metadata": metadata,
        },
    )
    candles = [
        (-60, "60000", "60020", "59990", "60010"),
        (0, "60010", "60050", "60000", "60040"),
        (60, "60040", "60100", "60030", "60090"),
    ]
    for offset, open_price, high, low, close in candles:
        open_epoch = START_EPOCH + offset
        _append(
            store,
            "btc_candle",
            datetime.fromtimestamp(open_epoch + 60, tz=UTC) + timedelta(milliseconds=10),
            {
                "source": "coinbase-exchange-rest",
                "product_id": "BTC-USD",
                "open_epoch": open_epoch,
                "close_epoch": open_epoch + 60,
                "interval_seconds": 60,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": "1",
                "candle_fingerprint": "f" * 64,
                "raw_observation_event_id": "raw",
                "response_sha256": "b" * 64,
                "causal_at_observation": True,
            },
        )
    health_at = START + timedelta(seconds=129)
    _append(
        store,
        "source_health",
        health_at,
        {
            "source": "polymarket-data-api",
            "status": "poll_ok",
            "detail": "ok",
            "raw_observation_event_id": None,
        },
    )


def _append_fill(
    store: AppendOnlyEventStore,
    *,
    trade_id: str,
    outcome: str,
    source_seconds: int,
    price: str,
    shares: str,
) -> None:
    source_time = START + timedelta(seconds=source_seconds)
    fill = NormalizedFill(
        source_trade_id=trade_id,
        market_id=MARKET,
        asset_id=f"asset-{outcome.lower()}",
        outcome_side=outcome,  # type: ignore[arg-type]
        side="BUY",
        source_timestamp=source_time,
        price=Decimal(price),
        shares=Decimal(shares),
        receive_timestamp=source_time + timedelta(milliseconds=100),
        local_ingest_id=f"ingest-{trade_id}",
    )
    _append(store, "normalized_fill", fill.receive_timestamp, fill.to_payload())


def test_bounded_replay_reproduces_feature_prediction_outcome_and_binding(
    tmp_path: Path,
) -> None:
    artifacts = _artifacts(tmp_path)
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _seed_market_inputs(store)
    _append_fill(
        store,
        trade_id="up-1",
        outcome="UP",
        source_seconds=20,
        price="0.44",
        shares="2",
    )
    state_processor = LiveStateProcessor(run_id=RUN_ID, store=store)
    state_processor.process_pending()

    tick_time = START + timedelta(seconds=130)
    builder = LiveStage3GFeatureBuilder(run_id=RUN_ID, store=store)
    tick = builder.build_tick(market_id=MARKET, tick_time=tick_time)
    assert tick.scorable is True
    scorer = LiveShadowScorer(
        run_id=RUN_ID,
        store=store,
        artifact_dir=artifacts,
        clock=lambda: START + timedelta(seconds=139, milliseconds=999),
        monotonic_clock=lambda: 100.0,
    )
    assert len(scorer.process_pending()) == 1

    _append_fill(
        store,
        trade_id="down-1",
        outcome="DOWN",
        source_seconds=140,
        price="0.51",
        shares="1",
    )
    state_result = state_processor.process_pending()
    assert state_result.pair_formation_count == 1
    binder = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store)
    binding_result = binder.process_pending()
    assert binding_result.bound_pair_count == 1

    audit = audit_bounded_shadow_replay(store, artifact_dir=artifacts)

    assert audit.feature_snapshot_count == 1
    assert audit.prediction_count == 1
    assert audit.pair_formation_count == 1
    assert audit.outcome_label_count == 1
    assert audit.score_binding_count == 1
