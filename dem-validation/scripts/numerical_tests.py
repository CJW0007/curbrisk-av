"""Portable independent numerical checks of current DEM and teacher PUDO inputs.

Requires existing pandas, numpy, openpyxl and scipy. It never imports upstream
AV-blocking calculation functions. Every source is read-only. Source directory
can be relocated with --source-dir; teacher workbook can be verified directly
with --pudo-workbook. Results are saved only in this delivery analysis folder.
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
import scipy
from scipy.stats import binomtest
from verify_source import verify_source

HERE = Path(__file__).resolve().parent
SHA = "06fdb2e928ab133f799015ae01323c991669ddcd"
DEFAULT_SOURCE = HERE.parent / "source_inputs" / ("av-blocking-analysis-" + SHA)
MONTHS = ["2025-03", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_clock(value):
    if pd.isna(value):
        return math.nan
    if isinstance(value, dt.datetime):
        value = value.time()
    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute + value.second / 60
    parts = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", str(value))
    if not parts:
        return math.nan
    hour, minute, second = [int(x or 0) for x in parts.groups()]
    if hour >= 24 or minute >= 60 or second >= 60:
        return math.nan
    return 60 * hour + minute + second / 60


def predictive_probability(n, exposure_days, horizon_days=30):
    """Gamma-Poisson/Jeffreys integral, computed stably without upstream code."""
    assert n >= 0 and exposure_days > 0 and horizon_days > 0
    return -math.expm1((n + 0.5) * math.log(exposure_days / (exposure_days + horizon_days)))


def close(actual, expected, tolerance=1e-12):
    assert math.isclose(actual, expected, abs_tol=tolerance, rel_tol=0), (actual, expected)


def read_dem_independently(source):
    verify_source(source)
    primary = source / "data/AV-Brick-Report.xlsx"
    scopes = source / "data/labels/scope_exclusions.csv"
    evidence = source / "data/labels/evidence_flags.csv"
    raw = pd.read_excel(primary, sheet_name="DEM Incidents", engine="openpyxl")
    raw = raw.loc[raw.Date.notna()].copy()
    raw["id"] = [f"INC-{i + 1:03d}" for i in range(len(raw))]
    raw["date"] = pd.to_datetime(raw.Date).dt.normalize()
    raw["month"] = raw.date.dt.strftime("%Y-%m")
    scope = pd.read_csv(scopes, dtype=str)
    excluded = scope.loc[scope.source.eq("primary"), "record"]
    covered = raw.loc[~raw.id.isin(excluded) & raw.month.isin(MONTHS)].copy()
    starts = covered["Time Event Started"].map(parse_clock).to_numpy(float)
    clears = covered["Time Event Cleared"].map(parse_clock).to_numpy(float)
    covered["duration"] = (clears - starts) % (24 * 60)
    # Re-express the frozen public H1/H2 rule specification. Higher-priority H1
    # excludes a narrative from H2. This checks the current convention, not truth.
    av = r"(?:waymos?|av'?s?|zoox)"
    collision = re.compile("|".join([
        rf"{av}\W+vs\.?\b", rf"\bvs\.?\W+{av}\b", r"hit the door of (?:a |the )?waymo",
        rf"\b{av}\b[^.]{{0,15}}\bhit\b", r"involved in a[^.]{0,20}accident",
    ]), re.I)
    emergency = re.compile("|".join([
        r"\bmedics?\b", r"\bambulance", r"\bsffd", r"\bfire\b", r"\btrapped", "shots",
        "actively investigating", r"(?:veh(?:icle)?\.?|multi veh)[^.]{0,10}accident",
    ]), re.I)
    life_threat = re.compile(r"unconc?s?cious|trapped|\bfire\b|shots", re.I)
    narratives = covered["Summary/Narrative"].fillna("").astype(str)
    covered["is_h2"] = narratives.map(lambda text: bool(emergency.search(text)) and not bool(collision.search(text)))
    covered["h2_severe"] = covered.is_h2 & narratives.map(lambda text: bool(life_threat.search(text)))
    overrides = pd.read_csv(evidence, dtype=str).set_index("incident_id").strict_hazard
    covered["strict_h2"] = covered.is_h2 & covered.id.map(overrides).fillna("H2").eq("H2")
    covered["strict_h2_severe"] = covered.strict_h2 & narratives.map(lambda text: bool(life_threat.search(text)))
    return covered, {str(p.relative_to(source)): digest(p) for p in [primary, scopes, evidence]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--pudo-workbook", type=Path, help="Verify teacher Sheet1 A7:D10 directly when available.")
    parser.add_argument("--output-dir", type=Path, default=HERE.parent / "results")
    args = parser.parse_args()
    source, hashes = read_dem_independently(args.source_dir)
    exposure = sum(calendar.monthrange(*map(int, month.split("-")))[1] for month in MONTHS)
    assert len(source) == 117
    assert exposure == 184
    assert np.isfinite(source.duration).all()
    close(float(source.duration.sum()), 6222)
    assert int(source.duration.ge(60).sum()) == 34
    assert source.id.is_unique
    assert source.loc[source.h2_severe, "id"].tolist() == ["INC-064", "INC-089", "INC-102"]
    assert int(source.is_h2.sum()) == 6
    assert int(source.h2_severe.sum()) == 3
    assert int(source.strict_h2.sum()) == 1
    assert int(source.strict_h2_severe.sum()) == 0
    h2_severe_probability = predictive_probability(int(source.h2_severe.sum()), exposure)
    h2_strict_probability = predictive_probability(int(source.strict_h2.sum()), exposure)
    close(h2_severe_probability, 0.41059451399633684)
    close(h2_strict_probability, 0.20272880325426046)
    # Six total H2 events are Major-or-worse, not six Severe events.
    close(predictive_probability(int(source.is_h2.sum()), exposure), 0.6253494946012341)
    assert h2_severe_probability < predictive_probability(int(source.is_h2.sum()), exposure)
    # Independent clock boundary checks protect the midnight/60-minute convention.
    assert (parse_clock("00:20") - parse_clock("23:40")) % 1440 == 40
    assert (parse_clock("01:00") - parse_clock("00:00")) % 1440 == 60
    assert (parse_clock("00:00") - parse_clock("00:00")) % 1440 == 0

    complaints = np.array([42, 66, 69, 79], dtype=int)
    trips = np.array([2676001, 3748532, 3905934, 4220075], dtype=int)
    pudo_provenance = {
        "source_status": "Teacher Sheet1 A7:D10 cached inputs provided for this delivery. Workbook cells not directly verified in this invocation.",
        "complaints": complaints.tolist(), "trips": trips.tolist(),
    }
    if args.pudo_workbook:
        table = pd.read_excel(args.pudo_workbook, sheet_name="Sheet1", header=None, engine="openpyxl")
        rows = table.iloc[6:10, :4].copy()
        # Teacher layout: Quarter, Trips, PUDO complaints v1, PUDO complaints v22.
        # The selected four quarters agree between complaint versions. Older
        # quarters differ and are deliberately outside the teacher comparison.
        extracted_counts = pd.to_numeric(rows.iloc[:, 3], errors="raise").to_numpy(int)
        extracted_trips = pd.to_numeric(rows.iloc[:, 1], errors="raise").to_numpy(int)
        np.testing.assert_array_equal(extracted_counts, complaints)
        np.testing.assert_array_equal(extracted_trips, trips)
        np.testing.assert_array_equal(pd.to_numeric(rows.iloc[:, 2], errors="raise").to_numpy(int), complaints)
        assert digest(args.pudo_workbook) == "2459c381e620234fe62ce50f0b5ffcb55fc16e0aaefd03e0352e45fe44cbf729"
        pudo_provenance.update({"source_status": "Teacher workbook cells directly verified.", "source_path_at_run": str(args.pudo_workbook.resolve()),
                                "sha256": digest(args.pudo_workbook), "sheet": "Sheet1", "range": "A7:D10",
                                "complaint_column": "D: PUDO complaints v22 (agrees with C: v1 in selected four quarters)", "trip_column": "B: Trips",
                                "period_labels": rows.iloc[:, 0].astype(str).tolist()})
    # Preserve the teacher comparison: first three quarters pooled versus fourth.
    earlier_count, recent_count = int(complaints[:3].sum()), int(complaints[3])
    earlier_trips, recent_trips = int(trips[:3].sum()), int(trips[3])
    assert (earlier_count, earlier_trips, recent_count, recent_trips) == (177, 10330467, 79, 4220075)
    earlier_rate, recent_rate = earlier_count / earlier_trips, recent_count / recent_trips
    rr = recent_rate / earlier_rate
    exposure_share = recent_trips / (earlier_trips + recent_trips)
    exact_p = float(binomtest(recent_count, earlier_count + recent_count, exposure_share, alternative="two-sided").pvalue)
    close(rr, 1.092580915452844)
    close(exact_p, 0.5353666932462805)
    # Pooling means summing counts and exposures, not averaging quarter rates.
    assert not math.isclose(earlier_rate, float(np.mean(complaints[:3] / trips[:3])), rel_tol=1e-6)
    result = {
        "status": "PASS",
        "source_commit": SHA,
        "source_sha256": hashes,
        "independence": "No upstream calculation imports. Raw spreadsheet clocks, source scope exclusions, frozen H1/H2 regex conventions and evidence overrides are re-expressed directly. This verifies conventions, not the clinical or scene truth of a label.",
        "dem": {"covered_records": len(source), "assumed_calendar_days": exposure, "logged_minutes": float(source.duration.sum()),
                "long_logged_events_ge_60": int(source.duration.ge(60).sum()), "h2_major_or_worse_count": int(source.is_h2.sum()),
                "h2_severe_count": int(source.h2_severe.sum()), "h2_severe_ids": source.loc[source.h2_severe, "id"].tolist(),
                "h2_severe_predictive_p_30d": h2_severe_probability, "strict_h2_major_count": int(source.strict_h2.sum()),
                "strict_h2_major_ids": source.loc[source.strict_h2, "id"].tolist(), "strict_h2_major_predictive_p_30d": h2_strict_probability},
        "pudo": {**pudo_provenance, "contrast": "fourth quarter versus first three quarters pooled", "earlier_complaints": earlier_count,
                 "earlier_trips": earlier_trips, "recent_complaints": recent_count, "recent_trips": recent_trips,
                 "earlier_complaints_per_million_trips": earlier_rate * 1e6, "recent_complaints_per_million_trips": recent_rate * 1e6,
                 "recent_over_earlier_rate_ratio": rr, "two_sided_exact_conditional_p": exact_p,
                 "test_null": "Equal complaint rates per trip. Conditional on 256 total complaints, recent count is Binomial(256, recent exposure share).",
                 "limitations": "Complaint sourcing and trip denominator eligibility must match. This is complaint frequency per trip, not injury risk or a causal AV comparison."},
        "environment": {"executable": sys.executable, "python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "scipy": scipy.__version__},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "numerical_test_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
