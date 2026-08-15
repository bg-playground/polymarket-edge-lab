from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast

import httpx

from polymarket_edge_lab.shadow.binding import ProspectiveOutcomeBinder
from polymarket_edge_lab.shadow.bounded_replay import (
    BoundedReplayAuditResult,
    audit_bounded_shadow_replay,
)
from polymarket_edge_lab.shadow.btc_collector import (
    COINBASE_EXCHANGE_API_BASE,
    GRANULARITY_SECONDS,
    PRODUCT_ID,
)
from polymarket_edge_lab.shadow.evaluation import (
    FROZEN_FEATURE_TICK_INTERVAL_SECONDS,
    FROZEN_TARGET_ACCOUNT,
    FROZEN_TARGET_POLL_INTERVAL_SECONDS,
    FrozenEvaluationConfig,
    start_frozen_evaluation,
    verify_frozen_evaluation,
)
from polymarket_edge_lab.shadow.events import EventEnvelope, EventType, NormalizedFill
from polymarket_edge_lab.shadow.feature_builder import LiveStage3GFeatureBuilder
from polymarket_edge_lab.shadow.market_metadata import GAMMA_API_BASE
from polymarket_edge_lab.shadow.scorer import LiveShadowScorer
from polymarket_edge_lab.shadow.state_processor import LiveStateProcessor
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore
from polymarket_edge_lab.shadow.target_collector import DATA_API_BASE

PREFLIGHT_SCHEMA_VERSION = "m4a-frozen-evaluation-preflight-v1"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_FIXTURE_RUN_ID = "m4a-preflight-disposable"
_FIXTURE_MARKET = "0x" + "9" * 64
_FIXTURE_START = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_FIXTURE_START_EPOCH = int(_FIXTURE_START.timestamp())

CheckStatus = Literal["pass", "fail"]
Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: CheckStatus
    reason_code: str
    detail: str


@dataclass(frozen=True)
class FrozenEvaluationPreflightReport:
    schema_version: str
    generated_at: str
    ready: bool
    run_id: str
    repository_commit: str
    event_log: str
    checks: list[PreflightCheck]
    artifact_manifest: dict[str, object] | None
    bounded_replay: BoundedReplayAuditResult | None


def json_dumps(report: FrozenEvaluationPreflightReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True)


def _pass(name: str, reason_code: str, detail: str) -> PreflightCheck:
    return PreflightCheck(name=name, status="pass", reason_code=reason_code, detail=detail)


def _fail(name: str, reason_code: str, detail: str) -> PreflightCheck:
    return PreflightCheck(name=name, status="fail", reason_code=reason_code, detail=detail)


def _git_output(repository_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _check_repository(repository_root: Path, repository_commit: str) -> PreflightCheck:
    expected = repository_commit.strip().lower()
    if _SHA40_RE.fullmatch(expected) is None:
        return _fail(
            "repository_commit",
            "repository_commit_not_full_sha",
            "repository commit must be an exact 40-character hexadecimal SHA",
        )
    try:
        head = _git_output(repository_root, "rev-parse", "HEAD").lower()
        status = _git_output(repository_root, "status", "--porcelain")
    except (OSError, subprocess.CalledProcessError) as exc:
        return _fail(
            "repository_commit",
            "repository_state_unavailable",
            f"could not inspect repository state: {type(exc).__name__}",
        )
    if head != expected:
        return _fail(
            "repository_commit",
            "repository_head_mismatch",
            f"HEAD {head} does not match requested launch commit {expected}",
        )
    if status:
        return _fail(
            "repository_commit",
            "repository_worktree_dirty",
            "repository worktree contains uncommitted changes",
        )
    return _pass(
        "repository_commit",
        "repository_commit_exact",
        f"clean repository HEAD matches {expected}",
    )


def _check_event_log_destination(event_log: Path) -> PreflightCheck:
    if event_log.exists():
        if not event_log.is_file():
            return _fail(
                "event_log_destination",
                "event_log_not_regular_file",
                "reserved evaluation-log path exists but is not a regular file",
            )
        if event_log.stat().st_size != 0:
            return _fail(
                "event_log_destination",
                "event_log_not_empty",
                "new frozen evaluation requires an empty event log",
            )
    parent = event_log.parent
    if not parent.exists() or not parent.is_dir():
        return _fail(
            "event_log_destination",
            "event_log_parent_missing",
            "evaluation-log parent directory must already exist",
        )
    try:
        fd, probe_name = tempfile.mkstemp(prefix=".m4a-preflight-", dir=parent)
        os.close(fd)
        Path(probe_name).unlink()
    except OSError as exc:
        return _fail(
            "event_log_destination",
            "event_log_parent_not_writable",
            f"could not create and remove a sibling probe file: {type(exc).__name__}",
        )
    state = "exists and is empty" if event_log.exists() else "does not yet exist"
    return _pass(
        "event_log_destination",
        "event_log_ready_for_sequence_zero",
        f"reserved evaluation-log path {state}; parent is writable",
    )


def _check_clocks(now: Clock, monotonic_clock: MonotonicClock) -> PreflightCheck:
    try:
        wall = now()
        first = monotonic_clock()
        second = monotonic_clock()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "clock_sanity",
            "clock_read_failed",
            f"clock read failed: {type(exc).__name__}",
        )
    if wall.tzinfo is None or wall.utcoffset() != timedelta(0):
        return _fail(
            "clock_sanity",
            "wall_clock_not_utc",
            "wall clock must be timezone-aware UTC",
        )
    if second < first:
        return _fail(
            "clock_sanity",
            "monotonic_clock_regressed",
            "monotonic clock decreased across consecutive reads",
        )
    return _pass(
        "clock_sanity",
        "utc_and_monotonic_clocks_ready",
        "timezone-aware UTC wall clock and non-regressing monotonic clock are available",
    )


def _evaluation_config(
    *,
    run_id: str,
    repository_commit: str,
    artifact_dir: Path,
) -> FrozenEvaluationConfig:
    return FrozenEvaluationConfig(
        run_id=run_id,
        repository_commit=repository_commit,
        artifact_dir=artifact_dir,
        target_account=FROZEN_TARGET_ACCOUNT,
        target_poll_interval_seconds=FROZEN_TARGET_POLL_INTERVAL_SECONDS,
        feature_tick_interval_seconds=FROZEN_FEATURE_TICK_INTERVAL_SECONDS,
    )


def _check_disposable_start_restart(
    *,
    config: FrozenEvaluationConfig,
    started_at: datetime,
) -> tuple[PreflightCheck, dict[str, object] | None]:
    try:
        with TemporaryDirectory(prefix="m4a-evaluation-preflight-") as temp_dir:
            store = AppendOnlyEventStore(Path(temp_dir) / "events.ndjson")
            start_frozen_evaluation(store=store, config=config, started_at=started_at)
            start = verify_frozen_evaluation(store=store, config=config)
            if store.next_sequence() != 1:
                raise ValueError("disposable start did not leave exactly one sequence-zero event")
            payload = start.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("disposable evaluation start payload is not an object")
            manifest = payload.get("artifact_manifest")
            if not isinstance(manifest, dict):
                raise ValueError("disposable evaluation start lacks artifact manifest")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return (
            _fail(
                "frozen_start_restart",
                "frozen_start_restart_failed",
                f"disposable frozen start/restart validation failed: {exc}",
            ),
            None,
        )
    return (
        _pass(
            "frozen_start_restart",
            "frozen_start_restart_verified",
            "artifacts/config validated and start/restart succeeded on a disposable log",
        ),
        manifest,
    )


def _append_fixture(
    store: AppendOnlyEventStore,
    event_type: EventType,
    created_at: datetime,
    payload: dict[str, object],
) -> str:
    sequence = store.next_sequence()
    event_id = f"{_FIXTURE_RUN_ID}:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type=event_type,
            event_id=event_id,
            run_id=_FIXTURE_RUN_ID,
            sequence=sequence,
            created_at=created_at,
            payload=payload,
        )
    )
    return event_id


def _seed_fixture_inputs(store: AppendOnlyEventStore) -> None:
    metadata = {
        "condition_id": _FIXTURE_MARKET,
        "gamma_market_id": "preflight-fixture",
        "slug": f"btc-updown-5m-{_FIXTURE_START_EPOCH}",
        "question": "Bitcoin Up or Down",
        "market_start_epoch": _FIXTURE_START_EPOCH,
        "market_end_epoch": _FIXTURE_START_EPOCH + 300,
        "up_token_id": "asset-up",
        "down_token_id": "asset-down",
        "active": True,
        "closed": False,
        "accepting_orders": True,
        "raw_observation_sha256": "a" * 64,
    }
    _append_fixture(
        store,
        "market_metadata",
        _FIXTURE_START,
        {
            "condition_id": _FIXTURE_MARKET,
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
        open_epoch = _FIXTURE_START_EPOCH + offset
        _append_fixture(
            store,
            "btc_candle",
            datetime.fromtimestamp(open_epoch + 60, tz=UTC) + timedelta(milliseconds=10),
            {
                "source": "coinbase-exchange-rest",
                "product_id": PRODUCT_ID,
                "open_epoch": open_epoch,
                "close_epoch": open_epoch + 60,
                "interval_seconds": GRANULARITY_SECONDS,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": "1",
                "candle_fingerprint": "f" * 64,
                "raw_observation_event_id": "preflight-raw",
                "response_sha256": "b" * 64,
                "causal_at_observation": True,
            },
        )
    _append_fixture(
        store,
        "source_health",
        _FIXTURE_START + timedelta(seconds=129),
        {
            "source": "polymarket-data-api",
            "status": "poll_ok",
            "detail": "preflight fixture",
            "raw_observation_event_id": None,
        },
    )


def _append_fixture_fill(
    store: AppendOnlyEventStore,
    *,
    trade_id: str,
    outcome: Literal["UP", "DOWN"],
    source_seconds: int,
    price: str,
    shares: str,
) -> None:
    source_time = _FIXTURE_START + timedelta(seconds=source_seconds)
    fill = NormalizedFill(
        source_trade_id=trade_id,
        market_id=_FIXTURE_MARKET,
        asset_id=f"asset-{outcome.lower()}",
        outcome_side=outcome,
        side="BUY",
        source_timestamp=source_time,
        price=Decimal(price),
        shares=Decimal(shares),
        receive_timestamp=source_time + timedelta(milliseconds=100),
        local_ingest_id=f"preflight-{trade_id}",
    )
    _append_fixture(store, "normalized_fill", fill.receive_timestamp, fill.to_payload())


def _run_disposable_bounded_replay(artifact_dir: Path) -> BoundedReplayAuditResult:
    with TemporaryDirectory(prefix="m4a-bounded-preflight-") as temp_dir:
        store = AppendOnlyEventStore(Path(temp_dir) / "events.ndjson")
        _seed_fixture_inputs(store)
        _append_fixture_fill(
            store,
            trade_id="up-1",
            outcome="UP",
            source_seconds=20,
            price="0.44",
            shares="2",
        )
        state_processor = LiveStateProcessor(run_id=_FIXTURE_RUN_ID, store=store)
        state_processor.process_pending()

        tick_time = _FIXTURE_START + timedelta(seconds=130)
        builder = LiveStage3GFeatureBuilder(run_id=_FIXTURE_RUN_ID, store=store)
        tick = builder.build_tick(market_id=_FIXTURE_MARKET, tick_time=tick_time)
        if not tick.scorable:
            raise ValueError(f"disposable fixture unscorable: {tick.reason_code}")
        scorer = LiveShadowScorer(
            run_id=_FIXTURE_RUN_ID,
            store=store,
            artifact_dir=artifact_dir,
            clock=lambda: _FIXTURE_START + timedelta(seconds=139, milliseconds=999),
            monotonic_clock=lambda: 100.0,
        )
        if len(scorer.process_pending()) != 1:
            raise ValueError("disposable fixture did not emit exactly one prediction")

        _append_fixture_fill(
            store,
            trade_id="down-1",
            outcome="DOWN",
            source_seconds=140,
            price="0.51",
            shares="1",
        )
        if state_processor.process_pending().pair_formation_count != 1:
            raise ValueError("disposable fixture did not form exactly one pair")
        binder = ProspectiveOutcomeBinder(run_id=_FIXTURE_RUN_ID, store=store)
        if binder.process_pending().bound_pair_count != 1:
            raise ValueError("disposable fixture did not create exactly one strict binding")
        return audit_bounded_shadow_replay(store, artifact_dir=artifact_dir)


def _check_bounded_replay(
    artifact_dir: Path,
) -> tuple[PreflightCheck, BoundedReplayAuditResult | None]:
    try:
        result = _run_disposable_bounded_replay(artifact_dir)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return (
            _fail(
                "bounded_replay",
                "bounded_replay_failed",
                f"disposable no-API bounded replay failed: {exc}",
            ),
            None,
        )
    expected = (1, 1, 1, 1, 1)
    actual = (
        result.feature_snapshot_count,
        result.prediction_count,
        result.pair_formation_count,
        result.outcome_label_count,
        result.score_binding_count,
    )
    if actual != expected:
        return (
            _fail(
                "bounded_replay",
                "bounded_replay_unexpected_coverage",
                f"expected one feature/prediction/pair/outcome/binding, got {actual}",
            ),
            result,
        )
    return (
        _pass(
            "bounded_replay",
            "bounded_replay_verified",
            "disposable no-API replay reproduced feature, prediction, pair, outcome, and binding",
        ),
        result,
    )


async def _get_json_list(
    client: httpx.AsyncClient,
    *,
    url: str,
    params: dict[str, str | int],
) -> list[object]:
    response = await client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("endpoint did not return a JSON list")
    return cast(list[object], payload)


async def _check_connectivity(
    *,
    client: httpx.AsyncClient,
    now: datetime,
) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    try:
        trades = await _get_json_list(
            client,
            url=f"{DATA_API_BASE}/trades",
            params={
                "user": FROZEN_TARGET_ACCOUNT,
                "offset": 0,
                "limit": 1,
                "takerOnly": "false",
            },
        )
        checks.append(
            _pass(
                "polymarket_target_source",
                "polymarket_target_source_reachable",
                f"Data API returned a valid list ({len(trades)} record(s) in probe)",
            )
        )
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
        checks.append(
            _fail(
                "polymarket_target_source",
                "polymarket_target_source_unready",
                f"Data API readiness probe failed: {type(exc).__name__}: {exc}",
            )
        )

    try:
        markets = await _get_json_list(
            client,
            url=f"{GAMMA_API_BASE}/markets",
            params={"limit": 1, "active": "true", "closed": "false"},
        )
        checks.append(
            _pass(
                "polymarket_market_metadata_source",
                "polymarket_market_metadata_source_reachable",
                f"Gamma API returned a valid list ({len(markets)} record(s) in probe)",
            )
        )
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
        checks.append(
            _fail(
                "polymarket_market_metadata_source",
                "polymarket_market_metadata_source_unready",
                f"Gamma API readiness probe failed: {type(exc).__name__}: {exc}",
            )
        )

    closed_boundary = int(now.timestamp())
    closed_boundary -= closed_boundary % GRANULARITY_SECONDS
    start = datetime.fromtimestamp(closed_boundary - 180, tz=UTC)
    end = datetime.fromtimestamp(closed_boundary, tz=UTC)
    try:
        candles = await _get_json_list(
            client,
            url=f"{COINBASE_EXCHANGE_API_BASE}/products/{PRODUCT_ID}/candles",
            params={
                "start": start.isoformat().replace("+00:00", "Z"),
                "end": end.isoformat().replace("+00:00", "Z"),
                "granularity": str(GRANULARITY_SECONDS),
            },
        )
        if not candles:
            raise ValueError("Coinbase candle probe returned no rows")
        first = candles[0]
        if not isinstance(first, list) or len(first) < 6:
            raise ValueError("Coinbase candle probe returned an invalid row")
        checks.append(
            _pass(
                "coinbase_btc_source",
                "coinbase_btc_source_reachable",
                f"Coinbase returned {len(candles)} structurally valid candle row(s)",
            )
        )
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
        checks.append(
            _fail(
                "coinbase_btc_source",
                "coinbase_btc_source_unready",
                f"Coinbase readiness probe failed: {type(exc).__name__}: {exc}",
            )
        )
    return checks


async def run_frozen_evaluation_preflight(
    *,
    run_id: str,
    repository_commit: str,
    repository_root: Path,
    artifact_dir: Path,
    event_log: Path,
    client: httpx.AsyncClient | None = None,
    now: Clock = lambda: datetime.now(tz=UTC),
    monotonic_clock: MonotonicClock = time.monotonic,
) -> FrozenEvaluationPreflightReport:
    """Validate launch readiness without starting or writing the reserved evaluation log."""
    generated_at = now().astimezone(UTC)
    checks = [
        _check_repository(repository_root, repository_commit),
        _check_event_log_destination(event_log),
        _check_clocks(now, monotonic_clock),
    ]
    config = _evaluation_config(
        run_id=run_id,
        repository_commit=repository_commit,
        artifact_dir=artifact_dir,
    )
    start_check, artifact_manifest = _check_disposable_start_restart(
        config=config,
        started_at=generated_at,
    )
    checks.append(start_check)
    replay_check, replay_result = _check_bounded_replay(artifact_dir)
    checks.append(replay_check)

    if client is None:
        async with httpx.AsyncClient(timeout=10.0) as owned_client:
            checks.extend(await _check_connectivity(client=owned_client, now=generated_at))
    else:
        checks.extend(await _check_connectivity(client=client, now=generated_at))

    return FrozenEvaluationPreflightReport(
        schema_version=PREFLIGHT_SCHEMA_VERSION,
        generated_at=generated_at.isoformat(),
        ready=all(check.status == "pass" for check in checks),
        run_id=run_id,
        repository_commit=repository_commit,
        event_log=str(event_log),
        checks=checks,
        artifact_manifest=artifact_manifest,
        bounded_replay=replay_result,
    )
