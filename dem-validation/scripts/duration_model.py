"""Small fixed-design exploratory comparison for logged DEM duration >=60 min.

No upstream imports, pretrained models, hyperparameter searches or new gold labels.
By default this reads the adjacent prepared feature CSV and source manifest.
--source-dir can instead independently reconstruct the feature CSV in memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, balanced_accuracy_score, brier_score_loss, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

from duration_data import HERE, DEFAULT_SOURCE, load_features

SEED = 20261005
THRESHOLD = 0.5
NUMERIC = ["n_avs", "n_avs_missing", "time_sin", "time_cos"]


def metric_set(labels, probabilities):
    labels, probabilities = np.asarray(labels), np.asarray(probabilities)
    predictions = (probabilities >= THRESHOLD).astype(int)
    two_classes = len(np.unique(labels)) == 2
    return {
        "n": len(labels), "positives": int(labels.sum()),
        "roc_auc": float(roc_auc_score(labels, probabilities)) if two_classes else None,
        "average_precision": float(average_precision_score(labels, probabilities)) if labels.sum() else None,
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "recall_at_0_5": float(recall_score(labels, predictions, zero_division=0)),
        "precision_at_0_5": float(precision_score(labels, predictions, zero_division=0)),
        "balanced_accuracy_at_0_5": float(balanced_accuracy_score(labels, predictions)) if two_classes else None,
        "predicted_positive_at_0_5": int(predictions.sum()),
    }


def fixed_models(include_area):
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    transforms = [("numeric", numeric, NUMERIC)]
    if include_area:
        transforms.append(("area", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["nominal_area"]))
    preprocess = ColumnTransformer(transforms, remainder="drop")
    estimators = {
        "dummy_prior": DummyClassifier(strategy="prior"),
        "logistic_l2": LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000),
        "shallow_tree": DecisionTreeClassifier(max_depth=3, min_samples_leaf=8, random_state=SEED),
    }
    return {name: Pipeline([("preprocess", clone(preprocess)), ("model", estimator)]) for name, estimator in estimators.items()}


def probability_one(fitted, features):
    positive_column = list(fitted.named_steps["model"].classes_).index(1)
    return fitted.predict_proba(features)[:, positive_column]


def plot_brier(metrics, output_dir):
    """Static scientific comparison; no uncertainty or significance is inferred."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ["Prevalence baseline", "L2 logistic", "Shallow tree"]
    values = [row["brier_score"] for row in metrics]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(7.6, 4.5))
    bars = ax.bar(labels, values, width=0.57, color=["#707782", "#2377A6", "#CD8740"])
    ax.set_ylim(0, 0.30)
    ax.set_ylabel("OOF Brier score (lower is better)")
    ax.set_title("Predicting long logged events", loc="left", pad=16, fontweight="bold")
    ax.yaxis.grid(True, color="#DEE2E7", linewidth=0.7)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.007, f"{value:.4f}", ha="center", va="bottom")
    fig.text(0.11, 0.08, "117 events; 34 with logged duration ≥60 minutes. Five folds group calendar dates.", fontsize=9)
    fig.text(0.11, 0.035, "Descriptive exploratory comparison. Both fitted models have greater probability error than the baseline.", fontsize=9)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    fig.savefig(output_dir / "model_brier.png", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features-file", type=Path, default=HERE.parent / "results/duration_features.csv")
    parser.add_argument("--source-manifest", type=Path, default=HERE.parent / "results/source_manifest.json")
    parser.add_argument("--source-dir", type=Path, help="Re-extract from this frozen source, rather than use --features-file.")
    parser.add_argument("--output-dir", type=Path, default=HERE.parent / "results")
    args = parser.parse_args()
    if args.source_dir:
        frame, manifest = load_features(args.source_dir)
        feature_origin = "reconstructed from --source-dir"
        feature_hash = None
    else:
        frame = pd.read_csv(args.features_file)
        manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        feature_origin = str(args.features_file.resolve())
        feature_hash = hashlib.sha256(args.features_file.read_bytes()).hexdigest()
    assert len(frame) == 117 and frame.long_logged_event.sum() == 34
    assert frame.incident_id.is_unique
    include_area = "nominal_area" in frame.columns
    features = NUMERIC + (["nominal_area"] if include_area else [])
    X, y = frame[features], frame.long_logged_event.to_numpy(int)
    groups = frame.date.to_numpy()
    splits = list(GroupKFold(n_splits=5).split(X, y, groups))
    models = fixed_models(include_area)
    oof = {name: np.full(len(frame), np.nan) for name in models}
    folds = np.full(len(frame), -1, dtype=int)
    fold_metrics = []
    fold_info = []
    for fold, (train, test) in enumerate(splits, 1):
        assert not set(groups[train]) & set(groups[test])
        assert len(np.unique(y[train])) == 2
        folds[test] = fold
        fold_info.append({"fold": fold, "train_n": len(train), "test_n": len(test), "train_positives": int(y[train].sum()),
                          "test_positives": int(y[test].sum()), "test_dates": sorted(set(groups[test]))})
        for name, pipeline in models.items():
            fitted = clone(pipeline).fit(X.iloc[train], y[train])
            oof[name][test] = probability_one(fitted, X.iloc[test])
            fold_metrics.append({"model": name, "fold": fold, **metric_set(y[test], oof[name][test])})
    assert (folds >= 1).all()
    assert all(np.isfinite(values).all() for values in oof.values())
    assert frame.assign(fold=folds).groupby("date").fold.nunique().eq(1).all()
    metrics = [{"model": name, **metric_set(y, probability)} for name, probability in oof.items()]
    baseline = metrics[0]
    for row in metrics:
        row["roc_auc_delta_vs_dummy"] = row["roc_auc"] - baseline["roc_auc"]
        row["average_precision_delta_vs_dummy"] = row["average_precision"] - baseline["average_precision"]
        row["brier_delta_vs_dummy"] = row["brier_score"] - baseline["brier_score"]
    prediction_table = frame[["incident_id", "excel_row", "date", "month", "long_logged_event"]].copy()
    prediction_table["fold"] = folds
    for name, values in oof.items():
        prediction_table[f"p_long_{name}"] = values

    # Fixed descriptive temporal check. These records were historically read,
    # so this is not untouched prospective validation and never selects a model.
    development = frame.month.isin(["2025-03", "2025-06", "2025-07"]).to_numpy()
    recent = frame.month.isin(["2025-08", "2025-09", "2025-10"]).to_numpy()
    assert development.sum() + recent.sum() == len(frame)
    temporal_metrics = []
    temporal_predictions = frame.loc[recent, ["incident_id", "date", "month", "long_logged_event"]].copy()
    if len(np.unique(y[development])) == 2 and recent.any():
        for name, pipeline in models.items():
            fitted = clone(pipeline).fit(X.loc[development], y[development])
            probability = probability_one(fitted, X.loc[recent])
            temporal_predictions[f"p_long_{name}"] = probability
            temporal_metrics.append({"model": name, **metric_set(y[recent], probability)})
    result = {
        "question": "Can recorded AV count, start clock time and supplied nominal area predict a logged event of at least 60 minutes better than a train-fold prevalence baseline?",
        "design_status": "New exploratory analysis, fixed before fitting. Not preregistered or causal.",
        "target": {"definition": "logged_duration_min >= 60", "n": len(frame), "positives": int(y.sum()), "prevalence": float(y.mean())},
        "features": features,
        "excluded_predictors": ["duration", "clear time", "cross-midnight flag", "duration-derived flags", "narrative", "hazard labels", "impact scores", "emergency/transit impact flags"],
        "preprocessing": "Within each training fold: numeric median imputation and standard scaling, explicit AV-count missing indicator, nominal-area one-hot encoding with unknown categories ignored. Clock sine/cosine is a deterministic transform of start time.",
        "models": {"dummy_prior": "DummyClassifier(strategy='prior')", "logistic_l2": "LogisticRegression(C=1, L2 default, lbfgs, max_iter=2000)",
                   "shallow_tree": "DecisionTreeClassifier(max_depth=3, min_samples_leaf=8, random_state=20261005)"},
        "cv": {"splitter": "GroupKFold(n_splits=5)", "group": "calendar DATE", "same_folds_for_every_model": True,
               "date_groups": int(frame.date.nunique()), "threshold_fixed_before_fit": THRESHOLD, "hyperparameter_tuning": False,
               "folds": fold_info},
        "oof_metrics": metrics,
        "fold_metrics": fold_metrics,
        "fold_spread_note": "Fold metrics show split variation only. The folds are dependent fits, so their spread is not a confidence interval.",
        "temporal_check": {"status": "Exploratory, historically read holdout, not untouched prospective validation",
                           "development_months": ["2025-03", "2025-06", "2025-07"], "recent_months": ["2025-08", "2025-09", "2025-10"],
                           "development_n": int(development.sum()), "development_positives": int(y[development].sum()),
                           "recent_n": int(recent.sum()), "recent_positives": int(y[recent].sum()), "metrics": temporal_metrics},
        "source_manifest": manifest,
        "prepared_feature_origin": feature_origin,
        "prepared_feature_sha256": feature_hash,
        "model_environment": {"executable": sys.executable, "python": platform.python_version(), "numpy": np.__version__,
                              "pandas": pd.__version__, "scipy": scipy.__version__, "scikit_learn": sklearn.__version__},
        "limitations": ["117 logged events and 34 positives offer limited precision.", "Grouping by date reduces shared-date leakage but cannot prove different dates are independent episodes.",
                        "Area codes come from an existing hand-coded workbook and are not independently adjudicated.", "Full-month coverage is the source assumption, not audited reporting completeness.",
                        "Recorded duration may reflect reporting and clearance practices; it does not measure emergency delay, person exposure or public harm.",
                        "No model is selected or promoted from this comparison. A useful absence of improvement is a valid finding."],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "model_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pd.DataFrame(metrics).to_csv(args.output_dir / "model_results.csv", index=False)
    prediction_table.to_csv(args.output_dir / "oof_predictions.csv", index=False)
    pd.DataFrame(fold_metrics).to_csv(args.output_dir / "fold_metrics.csv", index=False)
    temporal_predictions.to_csv(args.output_dir / "recent_period_predictions.csv", index=False)
    pd.DataFrame(temporal_metrics).to_csv(args.output_dir / "recent_period_metrics.csv", index=False)
    plot_brier(metrics, args.output_dir)
    print(pd.DataFrame(metrics).to_string(index=False))
    print("Recent-period exploratory check:")
    print(pd.DataFrame(temporal_metrics).to_string(index=False))


if __name__ == "__main__":
    main()
