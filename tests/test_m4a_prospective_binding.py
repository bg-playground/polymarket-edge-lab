from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_edge_lab.shadow.binding import ProspectiveOutcomeBinder
from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

RUN_ID = "run-bind"
MARKET = "0x" + "1" * 64
SOURCE_SECOND = datetime(2026, 8, 15, 12, 2, 10, tzinfo=UTC)


def _append_prediction(
    store: AppendOnlyEventStore,
    *,
    created_at: datetime,
    score_id: str,
    eligible: bool = True,
    event_conditioned: bool = False,
) -> str:
    sequence = store.next_sequence()
    event_id = f"{RUN_ID}:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type="prediction",
            event_id=event_id,
            run_id=RUN_ID,
            sequence=sequence,
            created_at=created_at,
            payload={
                "score_id": score_id,
                "market_id": MARKET,
                "advancement_eligible_candidate": eligible,
                "event_conditioned_reconstruction": event_conditioned,
            },
        )
    )
    return event_id


def _append_pair(
    store: AppendOnlyEventStore,
    *,
    pair_index: int = 0,
    pair_cost: str = "0.97",
    created_at: datetime | None = None,
) -> str:
    sequence = store.next_sequence()
    event_id = f"{RUN_ID}:{sequence}"
    receive_time = created_at or SOURCE_SECOND + timedelta(seconds=3)
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type="pair_formation",
            event_id=event_id,
            run_id=RUN_ID,
            sequence=sequence,
            created_at=receive_time,
            payload={
                "normalized_fill_event_id": "fill-1",
                "pair_index": pair_index,
                "market_id": MARKET,
                "completing_source_trade_id": "trade-completing",
                "up_source_trade_id": "trade-up",
                "down_source_trade_id": "trade-down",
                "paired_shares": "2.5",
                "up_price": "0.44",
                "down_price": "0.53",
                "pair_cost": pair_cost,
                "lag_seconds": 7,
                "formed_at_source_timestamp": SOURCE_SECOND.isoformat(),
                "formed_at_receive_timestamp": receive_time.isoformat(),
            },
        )
    )
    return event_id


def _bindings(store: AppendOnlyEventStore) -> list[dict[str, object]]:
    return [record for record in store.iter_records() if record["event_type"] == "score_binding"]


def _labels(store: AppendOnlyEventStore) -> list[dict[str, object]]:
    return [record for record in store.iter_records() if record["event_type"] == "outcome_label"]


def test_prediction_one_millisecond_before_source_second_binds(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    prediction_id = _append_prediction(
        store,
        created_at=SOURCE_SECOND - timedelta(milliseconds=1),
        score_id="score-prior",
    )
    pair_id = _append_pair(store)

    result = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store).process_pending()

    assert result.bound_pair_count == 1
    assert result.unbound_pair_count == 0
    binding = _bindings(store)[0]["payload"]
    assert isinstance(binding, dict)
    assert binding["pair_formation_event_id"] == pair_id
    assert binding["prediction_event_id"] == prediction_id
    assert binding["status"] == "bound_strictly_prior_score"


def test_prediction_exactly_at_source_second_is_excluded(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_prediction(store, created_at=SOURCE_SECOND, score_id="score-same-second")
    _append_pair(store)

    result = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store).process_pending()

    assert result.bound_pair_count == 0
    assert result.unbound_pair_count == 1
    binding = _bindings(store)[0]["payload"]
    assert isinstance(binding, dict)
    assert binding["status"] == "unbound_no_strictly_prior_score"
    assert binding["prediction_event_id"] is None


def test_latest_eligible_strictly_prior_prediction_wins(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_prediction(
        store,
        created_at=SOURCE_SECOND - timedelta(seconds=5),
        score_id="score-old",
    )
    expected = _append_prediction(
        store,
        created_at=SOURCE_SECOND - timedelta(milliseconds=1),
        score_id="score-latest",
    )
    _append_prediction(
        store,
        created_at=SOURCE_SECOND - timedelta(milliseconds=2),
        score_id="score-diagnostic",
        event_conditioned=True,
    )
    _append_pair(store)

    ProspectiveOutcomeBinder(run_id=RUN_ID, store=store).process_pending()

    binding = _bindings(store)[0]["payload"]
    assert isinstance(binding, dict)
    assert binding["prediction_event_id"] == expected
    assert binding["score_id"] == "score-latest"


def test_prediction_appended_after_pair_cannot_retroactively_bind(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_pair(store)
    _append_prediction(
        store,
        created_at=SOURCE_SECOND - timedelta(milliseconds=1),
        score_id="score-late-append",
    )

    result = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store).process_pending()

    assert result.unbound_pair_count == 1
    binding = _bindings(store)[0]["payload"]
    assert isinstance(binding, dict)
    assert binding["prediction_event_id"] is None


def test_multiple_pair_rows_from_same_fill_reuse_same_prior_prediction(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    prediction_id = _append_prediction(
        store,
        created_at=SOURCE_SECOND - timedelta(seconds=1),
        score_id="score-shared",
    )
    _append_pair(store, pair_index=0, pair_cost="0.96")
    _append_pair(store, pair_index=1, pair_cost="1.02")

    result = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store).process_pending()

    assert result.labeled_pair_count == 2
    assert result.bound_pair_count == 2
    bindings = _bindings(store)
    assert len(bindings) == 2
    for record in bindings:
        payload = record["payload"]
        assert isinstance(payload, dict)
        assert payload["prediction_event_id"] == prediction_id
    labels = _labels(store)
    assert len(labels) == 2
    favorable = []
    for record in labels:
        payload = record["payload"]
        assert isinstance(payload, dict)
        favorable.append(payload["favorable"])
    assert favorable == [True, False]


def test_restart_is_idempotent(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_prediction(
        store,
        created_at=SOURCE_SECOND - timedelta(seconds=1),
        score_id="score-prior",
    )
    _append_pair(store)

    first = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store).process_pending()
    before = list(store.iter_records())
    second = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store).process_pending()
    after = list(store.iter_records())

    assert first.labeled_pair_count == 1
    assert second.labeled_pair_count == 0
    assert before == after
