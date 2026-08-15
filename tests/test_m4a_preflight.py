from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import joblib
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.pipeline import Pipeline

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.shadow.preflight import run_frozen_evaluation_preflight
from polymarket_edge_lab.shadow.scorer import MODEL_NAMES

RUN_ID = "m4a-frozen-preflight-test"
NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


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
        regressor = Pipeline([("model", DummyRegressor(strategy="constant", constant=0.97))])
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


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "preflight@example.test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Preflight Test"], cwd=root, check=True)
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return root, commit


def _client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "data-api.polymarket.com":
            return httpx.Response(200, json=[])
        if request.url.host == "gamma-api.polymarket.com":
            return httpx.Response(200, json=[{"id": "probe"}])
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=[[1_723_728_000, 60000, 60100, 60010, 60090, 1]])
        return httpx.Response(404, json={"error": "unexpected probe"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_preflight_passes_without_creating_reserved_evaluation_log(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    repository_root, commit = _repository(tmp_path)
    event_log = tmp_path / "real-frozen-evaluation.ndjson"

    async def run() -> object:
        async with _client() as client:
            return await run_frozen_evaluation_preflight(
                run_id=RUN_ID,
                repository_commit=commit,
                repository_root=repository_root,
                artifact_dir=artifacts,
                event_log=event_log,
                client=client,
                now=lambda: NOW,
                monotonic_clock=lambda: 100.0,
            )

    report = asyncio.run(run())

    assert report.ready is True
    assert event_log.exists() is False
    assert report.artifact_manifest is not None
    assert report.bounded_replay is not None
    assert report.bounded_replay.feature_snapshot_count == 1
    assert report.bounded_replay.prediction_count == 1
    assert report.bounded_replay.pair_formation_count == 1
    assert report.bounded_replay.outcome_label_count == 1
    assert report.bounded_replay.score_binding_count == 1
    assert all(check.status == "pass" for check in report.checks)


def test_preflight_fails_closed_for_dirty_reserved_log_and_artifact_drift(
    tmp_path: Path,
) -> None:
    artifacts = _artifacts(tmp_path)
    repository_root, commit = _repository(tmp_path)
    event_log = tmp_path / "real-frozen-evaluation.ndjson"
    original = b"already-started-or-contaminated\n"
    event_log.write_bytes(original)
    regressor = artifacts / "hgb_all_pre_event" / "regressor.joblib"
    regressor.write_bytes(regressor.read_bytes() + b"drift")

    async def run() -> object:
        async with _client() as client:
            return await run_frozen_evaluation_preflight(
                run_id=RUN_ID,
                repository_commit=commit,
                repository_root=repository_root,
                artifact_dir=artifacts,
                event_log=event_log,
                client=client,
                now=lambda: NOW,
                monotonic_clock=lambda: 100.0,
            )

    report = asyncio.run(run())
    failures = {check.name: check.reason_code for check in report.checks if check.status == "fail"}

    assert report.ready is False
    assert failures["event_log_destination"] == "event_log_not_empty"
    assert failures["frozen_start_restart"] == "frozen_start_restart_failed"
    assert failures["bounded_replay"] == "bounded_replay_failed"
    assert event_log.read_bytes() == original
