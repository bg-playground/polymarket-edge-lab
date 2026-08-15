from __future__ import annotations

import json
from pathlib import Path

import joblib

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.models.stage3g_frozen import FROZEN_MODELS, fit_and_write_frozen_models


def _rows(count: int = 220) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    all_features = sorted({feature for features in MODEL_FEATURES.values() for feature in features})
    for index in range(count):
        row: dict[str, object] = {
            "window_id": f"2026-08-{7 + (index % 7):02d}",
            "paired_shares": float(1 + index % 5),
            "pair_cost": 0.92 + (index % 13) / 1000,
            "favorable": index % 4 != 0,
        }
        for feature_index, feature in enumerate(all_features):
            row[feature] = float((index + feature_index) % 17) / 10.0
        rows.append(row)
    return rows


def test_frozen_export_writes_loadable_artifacts_and_provenance(tmp_path: Path) -> None:
    metadata = fit_and_write_frozen_models(
        _rows(),
        output_dir=tmp_path,
        source_commit="stage3g-training-commit",
    )

    assert [item.model_name for item in metadata] == list(FROZEN_MODELS)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_commit"] == "stage3g-training-commit"
    assert len(manifest["models"]) == 4

    for item in metadata:
        model_dir = tmp_path / item.model_name
        assert item.features == list(MODEL_FEATURES[item.model_name])
        assert len(item.regressor_sha256) == 64
        assert len(item.classifier_sha256) == 64
        assert len(item.preprocessing_fingerprint) == 64
        regressor = joblib.load(model_dir / "regressor.joblib")
        classifier = joblib.load(model_dir / "classifier.joblib")
        width = len(item.features)
        sample = [[0.0] * width]
        assert len(regressor.predict(sample)) == 1
        assert classifier.predict_proba(sample).shape == (1, 2)


def test_export_is_deterministic_in_predictions(tmp_path: Path) -> None:
    rows = _rows()
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_meta = fit_and_write_frozen_models(rows, output_dir=left, source_commit="same")
    right_meta = fit_and_write_frozen_models(rows, output_dir=right, source_commit="same")

    for first, second in zip(left_meta, right_meta, strict=True):
        assert first.features == second.features
        assert first.preprocessing_fingerprint == second.preprocessing_fingerprint
        width = len(first.features)
        sample = [[0.25] * width]
        left_reg = joblib.load(left / first.model_name / "regressor.joblib")
        right_reg = joblib.load(right / second.model_name / "regressor.joblib")
        left_cls = joblib.load(left / first.model_name / "classifier.joblib")
        right_cls = joblib.load(right / second.model_name / "classifier.joblib")
        assert left_reg.predict(sample).tolist() == right_reg.predict(sample).tolist()
        assert left_cls.predict_proba(sample).tolist() == right_cls.predict_proba(sample).tolist()
