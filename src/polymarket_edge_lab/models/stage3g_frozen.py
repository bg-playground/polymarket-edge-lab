from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES

HGB_PARAMETERS: dict[str, Any] = {
    "learning_rate": 0.05,
    "max_depth": 3,
    "max_iter": 100,
    "min_samples_leaf": 100,
    "l2_regularization": 1.0,
    "random_state": 0,
}

FROZEN_MODELS = (
    "hgb_all_pre_event",
    "hgb_timing_inventory",
    "linear_timing_inventory",
    "hgb_timing_inventory_btc60",
)


@dataclass(frozen=True)
class FrozenModelMetadata:
    schema_version: str
    model_name: str
    features: list[str]
    model_family: str
    parameters: dict[str, Any]
    training_windows: list[str]
    training_row_count: int
    training_paired_share_weight: float
    source_commit: str
    python_version: str
    sklearn_version: str
    platform: str
    regressor_sha256: str
    classifier_sha256: str
    preprocessing_fingerprint: str


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


def _build_models(name: str) -> tuple[Pipeline, Pipeline]:
    if name.startswith("linear_"):
        regressor = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("model", Ridge(alpha=1.0)),
            ]
        )
        classifier = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("model", LogisticRegression(C=1.0, max_iter=1000, random_state=0)),
            ]
        )
        return regressor, classifier

    regressor = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(**HGB_PARAMETERS)),
        ]
    )
    classifier = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(**HGB_PARAMETERS)),
        ]
    )
    return regressor, classifier


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preprocessing_fingerprint(regressor: Pipeline, classifier: Pipeline) -> str:
    payload: dict[str, Any] = {}
    for key, pipeline in (("regressor", regressor), ("classifier", classifier)):
        imputer = pipeline.named_steps["imputer"]
        payload[key] = [float(value) for value in imputer.statistics_]
        scale = pipeline.named_steps.get("scale")
        if scale is not None:
            payload[f"{key}_scale_mean"] = [float(value) for value in scale.mean_]
            payload[f"{key}_scale_scale"] = [float(value) for value in scale.scale_]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def fit_and_write_frozen_models(
    rows: list[dict[str, Any]], *, output_dir: Path, source_commit: str
) -> list[FrozenModelMetadata]:
    """Fit the exact frozen Stage 3G candidates and write immutable artifact metadata."""
    if not rows:
        raise ValueError("training rows must not be empty")
    windows = sorted({str(row["window_id"]) for row in rows})
    weights = _weights(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_rows: list[FrozenModelMetadata] = []

    for name in FROZEN_MODELS:
        features = MODEL_FEATURES[name]
        matrix = _matrix(rows, features)
        regressor, classifier = _build_models(name)
        regressor.fit(
            matrix,
            [float(row["pair_cost"]) for row in rows],
            model__sample_weight=weights,
        )
        classifier.fit(
            matrix,
            [int(bool(row["favorable"])) for row in rows],
            model__sample_weight=weights,
        )

        model_dir = output_dir / name
        model_dir.mkdir(parents=True, exist_ok=True)
        regressor_path = model_dir / "regressor.joblib"
        classifier_path = model_dir / "classifier.joblib"
        joblib.dump(regressor, regressor_path)
        joblib.dump(classifier, classifier_path)

        parameters: dict[str, Any]
        family: str
        if name.startswith("linear_"):
            family = "ridge_plus_logistic"
            parameters = {
                "ridge_alpha": 1.0,
                "logistic_c": 1.0,
                "logistic_max_iter": 1000,
                "random_state": 0,
                "imputer": "median",
                "standard_scaler": True,
            }
        else:
            family = "hist_gradient_boosting"
            parameters = {**HGB_PARAMETERS, "imputer": "median"}

        metadata = FrozenModelMetadata(
            schema_version="m4a-model-artifact-v1",
            model_name=name,
            features=list(features),
            model_family=family,
            parameters=parameters,
            training_windows=windows,
            training_row_count=len(rows),
            training_paired_share_weight=sum(weights),
            source_commit=source_commit,
            python_version=sys.version.split()[0],
            sklearn_version=sklearn.__version__,
            platform=platform.platform(),
            regressor_sha256=_sha256(regressor_path),
            classifier_sha256=_sha256(classifier_path),
            preprocessing_fingerprint=_preprocessing_fingerprint(regressor, classifier),
        )
        (model_dir / "metadata.json").write_text(
            json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        metadata_rows.append(metadata)

    manifest = {
        "schema_version": "m4a-model-manifest-v1",
        "source_commit": source_commit,
        "models": [asdict(item) for item in metadata_rows],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata_rows
