"""Read the frozen DEM workbooks without importing or modifying upstream code.

Use the bundled Python for this extraction. The model is a separate script so
the fitting environment does not determine how the source is interpreted.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sys

import numpy as np
import pandas as pd
from verify_source import verify_source

HERE = Path(__file__).resolve().parent
SOURCE_SHA = "06fdb2e928ab133f799015ae01323c991669ddcd"
DEFAULT_SOURCE = HERE.parent / "source_inputs" / (
    "av-blocking-analysis-" + SOURCE_SHA
)
COVERED_MONTHS = ["2025-03", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10"]
LOCATION = "Location (include Street Type: St, Ave, Blvd, etc)"


def clock_minutes(value):
    if pd.isna(value):
        return np.nan
    if isinstance(value, dt.datetime):
        value = value.time()
    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute + value.second / 60
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", str(value))
    if not match:
        return np.nan
    hour, minute, second = [int(v or 0) for v in match.groups()]
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return np.nan
    return hour * 60 + minute + second / 60


def join_key(dates, locations):
    normal_location = locations.astype("string").str.upper().str.replace(
        r"\s+", " ", regex=True
    ).str.strip()
    return pd.to_datetime(dates).dt.strftime("%Y-%m-%d") + "|" + normal_location


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_features(source_dir: Path):
    verify_source(source_dir)
    primary = source_dir / "data/AV-Brick-Report.xlsx"
    quant = source_dir / "data/AV-Brick-Report-analyzed.xlsx"
    scope_file = source_dir / "data/labels/scope_exclusions.csv"
    raw = pd.read_excel(primary, sheet_name="DEM Incidents", engine="openpyxl")
    raw = raw.loc[raw.Date.notna()].copy()
    raw["excel_row"] = raw.index + 2
    raw["incident_id"] = [f"INC-{i + 1:03d}" for i in range(len(raw))]
    raw["date"] = pd.to_datetime(raw.Date).dt.normalize()
    raw["month"] = raw.date.dt.strftime("%Y-%m")
    raw["start_min"] = raw["Time Event Started"].map(clock_minutes)
    raw["clear_min"] = raw["Time Event Cleared"].map(clock_minutes)
    # Source convention: wrap one midnight, never infer a multi-day interval.
    raw["logged_duration_min"] = (raw.clear_min - raw.start_min) % 1440
    raw["n_avs"] = pd.to_numeric(raw["Number of AVs Involved"], errors="coerce")
    raw["n_avs_missing"] = raw.n_avs.isna().astype(int)
    raw["key"] = join_key(raw.date, raw[LOCATION])
    scope = pd.read_csv(scope_file, dtype=str)
    excluded = scope.loc[scope.source.eq("primary"), "record"].tolist()
    covered = raw.loc[
        ~raw.incident_id.isin(excluded) & raw.month.isin(COVERED_MONTHS)
    ].copy()
    frame = covered.loc[covered.logged_duration_min.notna()].copy()

    area_info = {"included": False, "reason": "Analyzed area-code workbook unavailable."}
    source_files = [primary, scope_file]
    if quant.exists():
        source_files.append(quant)
        zones = pd.read_excel(quant, sheet_name="DEM Incidents Quant", engine="openpyxl")
        zones = zones.loc[pd.to_datetime(zones.Date, errors="coerce").notna()].copy()
        zones["key"] = join_key(pd.to_datetime(zones.Date), zones.iloc[:, 1])
        zones["zone"] = pd.to_numeric(zones.iloc[:, 2], errors="coerce")
        relevant = zones.loc[zones.key.isin(frame.key)]
        conflicts = relevant.groupby("key").zone.nunique().gt(1)
        invalid = relevant.zone.notna() & ~relevant.zone.isin(range(1, 11))
        area_info = {
            "included": not bool(conflicts.any() or invalid.any()),
            "join": "calendar date plus uppercase, whitespace-normalized location",
            "source_sheet": "DEM Incidents Quant",
            "source_column": str(zones.columns[2]),
            "conflicting_matched_keys": conflicts[conflicts].index.tolist(),
            "invalid_matched_zone_rows": int(invalid.sum()),
            "primary_duplicate_keys": int(frame.key.duplicated().sum()),
            "quant_duplicate_keys": int(zones.key.duplicated().sum()),
            "interpretation": "Supplied hand-coded zone 1-10 treated as nominal, not ordered.",
        }
        if area_info["included"]:
            # Identical duplicate zone labels are safe. A conflicting label is never chosen.
            one_zone = relevant.dropna(subset=["zone"]).drop_duplicates("key")
            frame = frame.merge(one_zone[["key", "zone"]], how="left", on="key", validate="many_to_one")
            frame["nominal_area"] = frame.zone.map(
                lambda v: "__missing__" if pd.isna(v) else f"zone_{int(v)}"
            )
            area_info["missing_area_records"] = int(frame.zone.isna().sum())
            area_info["matched_area_records"] = int(frame.zone.notna().sum())
            area_info["reason"] = "No conflicting matched keys or invalid area codes. Missing matches retain an explicit category."
        else:
            area_info["reason"] = "Area omitted because matched join keys conflict or matched codes fall outside 1-10."

    frame["time_sin"] = np.sin(2 * math.pi * frame.start_min / 1440)
    frame["time_cos"] = np.cos(2 * math.pi * frame.start_min / 1440)
    frame["long_logged_event"] = frame.logged_duration_min.ge(60).astype(int)
    columns = ["incident_id", "excel_row", "date", "month", "start_min", "n_avs", "n_avs_missing",
               "time_sin", "time_cos", "logged_duration_min", "long_logged_event"]
    if area_info["included"]:
        columns.append("nominal_area")
    result = frame[columns].copy()
    result["date"] = result.date.dt.strftime("%Y-%m-%d")
    manifest = {
        "source_commit": SOURCE_SHA,
        "source_dir_at_run": str(source_dir.resolve()),
        "source_sha256": {str(p.relative_to(source_dir)): sha256(p) for p in source_files},
        "primary_sheet": "DEM Incidents",
        "raw_primary_records": len(raw),
        "covered_records": len(covered),
        "finite_duration_records": len(result),
        "scope_excluded_ids": excluded,
        "covered_months": COVERED_MONTHS,
        "assumed_covered_calendar_days": sum(calendar.monthrange(*map(int, m.split("-")))[1] for m in COVERED_MONTHS),
        "duration_total_minutes": float(result.logged_duration_min.sum()),
        "positive_records_duration_ge_60": int(result.long_logged_event.sum()),
        "missing_av_counts": int(result.n_avs_missing.sum()),
        "missing_start_times": int(result.start_min.isna().sum()),
        "distinct_calendar_dates": int(result.date.nunique()),
        "area": area_info,
        "extraction_environment": {"executable": sys.executable, "python": platform.python_version(),
                                   "pandas": pd.__version__, "numpy": np.__version__},
        "duration_rule": "(clear clock minute - start clock minute) modulo 1440; original workbook Duration column is not used",
        "label_status": "An operational cutoff on logged duration. No new hazard, impact, causation or ground-truth labels.",
    }
    assert len(result) == 117, "Unexpected frozen-source record count."
    assert manifest["assumed_covered_calendar_days"] == 184
    assert result.logged_duration_min.sum() == 6222
    assert result.long_logged_event.sum() == 34
    assert result.incident_id.is_unique
    return result, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=HERE.parent / "results")
    args = parser.parse_args()
    frame, manifest = load_features(args.source_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output_dir / "duration_features.csv", index=False)
    (args.output_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"n": len(frame), "long_events": int(frame.long_logged_event.sum()), "dates": frame.date.nunique(), "area": manifest["area"]}, indent=2))


if __name__ == "__main__":
    main()
