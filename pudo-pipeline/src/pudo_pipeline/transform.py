"""Stage 2: parse extracted CSVs into tidy Polars frames.

Outputs
-------
complaints    one row per analytically relevant reported event, nullable Y/N
              flags, tagged with period_id / year / quarter / company.
monthly       one row per (year, month) of fleet activity (trips, VMT, PMT).
locations     one row per tract in the Incidents-Location source.
summary       one row per reporting period: PUDO counts joined to exposure,
              with complaints-per-100k-VMT rates.

Notes
-----
* TCPID is the carrier's CPUC permit number - it identifies Waymo, not a
  record. There is no row-level join key across files; complaint counts and
  VMT join at the reporting-period level.
* TimeofIncident is redacted, so complaints carry period-level dates only
  (month is null). Month_Level has true Year/Month, so quarter columns there
  are real calendar quarters.
* Per-row "Redacted" strings become nulls and are never converted to False.
* 2025+ source files contain millions of repeated all-N template rows.  The
  analytic event output retains rows with at least one positive relevant flag;
  raw source files remain the audit record.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from .config import (
    COMPANY,
    COMPANY_TCPIDS,
    COMPLAINT_FLAGS,
    COLLISION_PUDO_FLAGS,
    COLLISION_SEVERITY_FLAGS,
    LEGACY_COUNT_MAP,
    LEGACY_OPTIONAL_COUNT_MAP,
    MONTH_LEVEL_KEEP,
    PERIODS,
    PUDO_SEVERITY_MAP,
    PUDO_WORST_SEVERITY_COLUMNS,
    SUMMARY_OPTIONAL_COUNTS,
)


class DataValidationError(ValueError):
    """Raised when source data are present but cannot support valid rates."""


def _csv_columns(path: Path) -> list[str]:
    """Read only the CSV header without scanning a multi-million-row part."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle))


def _read_csv_str(
    path: Path,
    columns: Sequence[str] | None = None,
    positive_filter_columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Read selected columns as strings and normalize redaction to null.

    When ``positive_filter_columns`` is supplied, Polars applies the filter
    while scanning.  This prevents CPUC's multi-million-row all-N template
    parts from being materialized as pretend incidents.
    """
    lazy = pl.scan_csv(
        path,
        infer_schema_length=0,
        ignore_errors=True,
    )
    if columns is not None:
        lazy = lazy.select(list(columns))
    lazy = lazy.with_columns(
        pl.all()
        .str.strip_chars()
        .replace(["Redacted", "REDACTED", "NULL", "null", ""], None)
    )
    if positive_filter_columns:
        present = [c for c in positive_filter_columns if c in lazy.collect_schema()]
        if present:
            lazy = lazy.filter(
                pl.any_horizontal(
                    [pl.col(c).str.to_uppercase().eq("Y").fill_null(False) for c in present]
                )
            )
    return lazy.collect(engine="streaming")


def _flag_to_bool(col: str) -> pl.Expr:
    """Map Y/N to nullable booleans; redacted/blank stays unknown."""
    return (
        pl.when(pl.col(col) == "Y")
        .then(True)
        .when(pl.col(col) == "N")
        .then(False)
        .otherwise(None)
        .alias(col)
    )


def _numeric_expr(col: str, dtype: pl.DataType = pl.Float64) -> pl.Expr:
    """Parse CPUC numbers such as ``"1,430,498.32"`` without data loss."""
    return pl.col(col).str.replace_all(",", "").cast(dtype, strict=False).alias(col)


def _is_driverless_source(path: Path) -> bool:
    """Exclude legacy Drivered folders while accepting generic/new paths."""
    source = str(path).lower()
    return not ("drivered" in source and "driverless" not in source)


def _is_month_summary_source(path: Path) -> bool:
    """Recognize CPUC's month-summary filenames without matching tract files.

    CPUC called these ``Month_Level`` through 2025 and changed to
    ``Month_Part0`` in 2026. ``Monthly_Tract`` is a different, much larger
    table and must not be treated as the fleet-level denominator.
    """
    name = path.name.lower().replace(" ", "_").replace("-", "_")
    return "month_level" in name or "month_part" in name


def _is_incidents_location_source(path: Path) -> bool:
    """Recognize tract-level incident location files across name variants."""
    name = path.name.lower().replace(" ", "_").replace("-", "_")
    return "incidents_location" in name


def _waymo_rows(df: pl.DataFrame, path: Path) -> pl.DataFrame:
    if "TCPID" not in df.columns:
        raise DataValidationError(f"{path} has no TCPID column")
    return df.filter(
        pl.col("TCPID")
        .str.strip_chars()
        .str.to_uppercase()
        .is_in(sorted(COMPANY_TCPIDS))
    )


def _metadata_columns(period_id: str, source: Path, grain: str) -> list[pl.Expr]:
    meta = _period_meta(period_id)
    return [
        pl.lit(meta["period_id"]).alias("period_id"),
        pl.lit(meta["year"]).cast(pl.Int32).alias("year"),
        pl.lit(meta["quarter"]).cast(pl.Int8).alias("quarter"),
        pl.lit(None, dtype=pl.Int8).alias("month"),
        pl.lit(meta["company"]).alias("company"),
        pl.lit(source.name).alias("source_file"),
        pl.lit(grain).alias("record_grain"),
    ]


def _canonical_row_level(df: pl.DataFrame, period_id: str, source: Path) -> pl.DataFrame:
    required = {"ComplaintPUDO", "PUDOTravelLane"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise DataValidationError(f"{source} is missing row-level columns: {missing}")

    collision_cols = [c for c in COLLISION_PUDO_FLAGS if c in df.columns]
    if not collision_cols:
        raise DataValidationError(f"{source} has no row-level PUDO collision columns")

    kept_flags = [
        c
        for c in COMPLAINT_FLAGS + COLLISION_PUDO_FLAGS + COLLISION_SEVERITY_FLAGS
        if c in df.columns
    ]
    out = df.select(["TCPID"] + kept_flags).with_columns(
        [_flag_to_bool(c) for c in kept_flags]
    )
    out = out.with_columns(
        pl.any_horizontal(
            [pl.col(c).fill_null(False) for c in collision_cols]
        ).alias("CollisionPUDOAny")
    )
    present_severity = {
        canonical: raw
        for canonical, raw in PUDO_SEVERITY_MAP.items()
        if raw in out.columns
    }
    out = out.with_columns(
        [
            (pl.col(raw).fill_null(False) & pl.col("CollisionPUDOAny"))
            .cast(pl.Int64)
            .alias(canonical)
            for canonical, raw in present_severity.items()
        ]
        + [
            pl.lit(None, dtype=pl.Int64).alias(canonical)
            for canonical in PUDO_SEVERITY_MAP
            if canonical not in present_severity
        ]
        + [
            (pl.col("ComplaintPUDO").fill_null(False) & pl.col("CollisionPUDOAny"))
            .cast(pl.Int64)
            .alias("PUDOComplaintCollisionOverlap")
        ]
    )
    severity_order = [
        ("Fatality", "CollisionSeverityFatality"),
        ("Severe injury", "CollisionSeverityInjurySevere"),
        ("Minor injury", "CollisionSeverityInjuryMinor"),
        ("Possible injury", "CollisionSeverityInjuryPossible"),
        ("Property damage", "CollisionSeverityPropertyDamage"),
    ]
    worst = pl.lit("No listed severity flag")
    for label, raw in reversed(severity_order):
        if raw in out.columns:
            worst = pl.when(pl.col(raw).fill_null(False)).then(pl.lit(label)).otherwise(worst)
    out = out.with_columns(
        pl.when(pl.col("CollisionPUDOAny"))
        .then(worst)
        .otherwise(None)
        .alias("PUDOCollisionWorstSeverity")
    ).with_columns(
        [
            (
                (pl.col("PUDOCollisionWorstSeverity") == label)
                .fill_null(False)
                .cast(pl.Int64)
                .alias(column)
            )
            for label, column in PUDO_WORST_SEVERITY_COLUMNS.items()
        ]
        + [
            (
                pl.col("CollisionPUDOAny")
                & (
                    pl.any_horizontal(
                        [
                            pl.col(c).fill_null(False)
                            for c in present_severity.values()
                        ]
                    )
                    if present_severity
                    else pl.lit(False)
                )
            )
            .cast(pl.Int64)
            .alias("PUDOCollisionSeverityAnyPositive"),
            pl.col("PUDOCollisionWorstSeverity")
            .is_in(["Minor injury", "Severe injury", "Fatality"])
            .fill_null(False)
            .cast(pl.Int64)
            .alias("PUDOCollisionSeverityMinorOrWorse"),
        ]
    ).with_columns(
        [pl.col(c).cast(pl.Int64) for c in kept_flags + ["CollisionPUDOAny"]]
    )
    return out.with_columns(_metadata_columns(period_id, source, "row_level"))


def _canonical_legacy(df: pl.DataFrame, period_id: str, source: Path) -> pl.DataFrame:
    missing = sorted(set(LEGACY_COUNT_MAP.values()) - set(df.columns))
    if missing:
        raise DataValidationError(f"{source} is missing legacy aggregate columns: {missing}")

    optional = {
        canonical: old
        for canonical, old in LEGACY_OPTIONAL_COUNT_MAP.items()
        if old in df.columns
    }
    mappings = {**LEGACY_COUNT_MAP, **optional}
    expressions = [
        _numeric_expr(old, pl.Int64).alias(canonical)
        for canonical, old in mappings.items()
    ]
    out = df.select(["TCPID"] + list(mappings.values())).with_columns(
        expressions
    ).select(["TCPID"] + list(mappings))
    # Some legacy reports redact travel-lane totals.  Preserve that as null;
    # it is not equivalent to a reported zero.  Complaint and collision totals
    # are required for the primary analysis.
    critical = ["ComplaintPUDO", "CollisionPUDOAny"]
    if out.select(pl.any_horizontal([pl.col(c).is_null() for c in critical])).item():
        raise DataValidationError(f"{source} contains unparseable legacy PUDO counts")
    # Legacy severity totals cover all collisions. They cannot be linked back
    # specifically to the aggregate PUDO collision count.
    out = out.with_columns(
        [pl.lit(None, dtype=pl.Int64).alias(c) for c in PUDO_SEVERITY_MAP]
        + [pl.lit(None, dtype=pl.Utf8).alias("PUDOCollisionWorstSeverity")]
        + [pl.lit(None, dtype=pl.Int64).alias(c) for c in PUDO_WORST_SEVERITY_COLUMNS.values()]
        + [
            pl.lit(None, dtype=pl.Int64).alias("PUDOCollisionSeverityAnyPositive"),
            pl.lit(None, dtype=pl.Int64).alias("PUDOCollisionSeverityMinorOrWorse"),
            pl.lit(None, dtype=pl.Int64).alias("PUDOComplaintCollisionOverlap"),
        ]
    )
    return out.with_columns(_metadata_columns(period_id, source, "period_aggregate"))


def _period_meta(period_id: str) -> dict:
    months = PERIODS[period_id][1]
    first_year, first_month = months[0]
    last_year, last_month = months[-1]

    start = date(first_year, first_month, 1)
    stop = (
        date(last_year + 1, 1, 1)
        if last_month == 12
        else date(last_year, last_month + 1, 1)
    )
    midpoint = start + (stop - start) / 2

    base_months = next(iter(PERIODS.values()))[1]
    base_start = date(base_months[0][0], base_months[0][1], 1)
    base_last_year, base_last_month = base_months[-1]
    base_stop = (
        date(base_last_year + 1, 1, 1)
        if base_last_month == 12
        else date(base_last_year, base_last_month + 1, 1)
    )
    base_midpoint = base_start + (base_stop - base_start) / 2
    return {
        "period_id": period_id,
        "year": last_year,
        "quarter": (last_month - 1) // 3 + 1,  # quarter of period end
        "period_midpoint": midpoint.isoformat(),
        "time_months": (midpoint - base_midpoint).days / 30.4375,
        "company": COMPANY,
    }


def load_complaints(extract_dir: Path) -> pl.DataFrame:
    frames = []
    for period_id in PERIODS:
        pdir = extract_dir / period_id
        if not pdir.exists():
            continue
        files = sorted(
            f
            for f in pdir.rglob("*.csv")
            if "complaint" in f.name.lower().replace("-", "_")
            and _is_driverless_source(f)
        )
        for f in files:
            source_columns = _csv_columns(f)
            if "ComplaintPUDO" in source_columns:
                wanted = [
                    c
                    for c in [
                        "TCPID",
                        *COMPLAINT_FLAGS,
                        *COLLISION_PUDO_FLAGS,
                        *COLLISION_SEVERITY_FLAGS,
                    ]
                    if c in source_columns
                ]
            elif "ComplaintsPUDO" in source_columns:
                wanted = [
                    c
                    for c in [
                        "TCPID",
                        *LEGACY_COUNT_MAP.values(),
                        *LEGACY_OPTIONAL_COUNT_MAP.values(),
                    ]
                    if c in source_columns
                ]
            else:
                raise DataValidationError(f"Unrecognized complaints schema in {f}")
            df = _waymo_rows(
                _read_csv_str(
                    f,
                    wanted,
                    positive_filter_columns=(
                        [
                            *COMPLAINT_FLAGS,
                            *COLLISION_PUDO_FLAGS,
                            *COLLISION_SEVERITY_FLAGS,
                        ]
                        if "ComplaintPUDO" in source_columns
                        else None
                    ),
                ),
                f,
            )
            if df.height == 0:
                continue
            if "ComplaintPUDO" in df.columns:
                frames.append(_canonical_row_level(df, period_id, f))
            elif "ComplaintsPUDO" in df.columns:
                frames.append(_canonical_legacy(df, period_id, f))
            else:
                raise DataValidationError(f"Unrecognized complaints schema in {f}")
    if not frames:
        raise FileNotFoundError(f"No complaint CSVs found under {extract_dir}")
    return pl.concat(frames, how="diagonal")


def load_collision_locations(extract_dir: Path) -> pl.DataFrame:
    """Load tract aggregates used as the authoritative 2025+ collision count.

    Incident actor flags can miss collisions whose subtype is not published.
    Location aggregates therefore supply frequency, while incident rows retain
    their separate role for actor and severity cross-tabs.
    """
    frames = []
    required = [
        "TCPID",
        "Year",
        "Quarter",
        "Tract",
        "CollisionsAll",
        "CollisionsPUDO",
        "PUDOTravelLane",
    ]
    for period_id in PERIODS:
        pdir = extract_dir / period_id
        if not pdir.exists():
            continue
        files = sorted(
            f
            for f in pdir.rglob("*.csv")
            if _is_incidents_location_source(f) and _is_driverless_source(f)
        )
        for f in files:
            source_columns = _csv_columns(f)
            missing = sorted(set(required) - set(source_columns))
            if missing:
                raise DataValidationError(f"{f} is missing location columns: {missing}")
            df = _waymo_rows(_read_csv_str(f, required), f)
            if df.height == 0:
                continue
            frame = df.with_columns(
                _numeric_expr("CollisionsAll", pl.Int64),
                _numeric_expr("CollisionsPUDO", pl.Int64),
                _numeric_expr("PUDOTravelLane", pl.Int64),
                *_metadata_columns(period_id, f, "tract_aggregate"),
            )
            if frame.select(
                pl.any_horizontal(
                    pl.col("CollisionsAll").is_null(),
                    pl.col("CollisionsPUDO").is_null(),
                ).any()
            ).item():
                raise DataValidationError(f"{f} contains unparseable collision counts")
            frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"No Incidents-Location CSVs found under {extract_dir}")
    return pl.concat(frames, how="diagonal").unique(
        subset=[
            "period_id",
            "TCPID",
            "Year",
            "Quarter",
            "Tract",
            "CollisionsAll",
            "CollisionsPUDO",
            "PUDOTravelLane",
        ],
        keep="last",
    )


def load_monthly(extract_dir: Path) -> pl.DataFrame:
    frames = []
    for period_id in PERIODS:
        pdir = extract_dir / period_id
        if not pdir.exists():
            continue
        for f in sorted(pdir.rglob("*.csv")):
            if not _is_month_summary_source(f):
                continue
            if not _is_driverless_source(f):
                continue
            source_columns = _csv_columns(f)
            wanted = [c for c in MONTH_LEVEL_KEEP if c in source_columns]
            df = _waymo_rows(_read_csv_str(f, wanted), f)
            if df.height == 0:
                continue
            keep = [c for c in MONTH_LEVEL_KEEP if c in df.columns]
            required = {
                "TCPID",
                "Year",
                "Month",
                "TotalTrips",
                "TotalVMTPeriod1",
                "TotalVMTPeriod2",
                "TotalVMTPeriod3",
            }
            missing = sorted(required - set(keep))
            if missing:
                raise DataValidationError(f"{f} is missing Month-Level columns: {missing}")
            df = df.select(keep).with_columns(
                pl.lit(period_id).alias("period_id"),
                pl.lit(COMPANY).alias("company"),
                pl.lit(f.name).alias("source_file"),
            )
            frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No Month_Level CSVs found under {extract_dir}")
    out = pl.concat(frames, how="diagonal")
    numeric = [c for c in MONTH_LEVEL_KEEP if c != "TCPID" and c in out.columns]
    out = out.with_columns(
        [_numeric_expr(c) for c in numeric]
    ).with_columns(
        pl.col("Year").cast(pl.Int32).alias("year"),
        pl.col("Month").cast(pl.Int8).alias("month"),
    )
    out = out.with_columns(
        ((pl.col("month") - 1) // 3 + 1).cast(pl.Int8).alias("quarter"),
        (
            pl.col("TotalVMTPeriod1").fill_null(0)
            + pl.col("TotalVMTPeriod2").fill_null(0)
            + pl.col("TotalVMTPeriod3").fill_null(0)
        ).alias("vmt_total"),
    )
    critical = [
        "year",
        "month",
        "TotalTrips",
        "TotalVMTPeriod1",
        "TotalVMTPeriod2",
        "TotalVMTPeriod3",
        "vmt_total",
    ]
    null_counts = out.select([pl.col(c).null_count().alias(c) for c in critical]).row(0)
    bad = {c: count for c, count in zip(critical, null_counts) if count}
    if bad:
        raise DataValidationError(f"Unparseable Month-Level values: {bad}")
    if out.filter((pl.col("TotalTrips") < 0) | (pl.col("vmt_total") <= 0)).height:
        raise DataValidationError("Month-Level data contain negative trips or non-positive VMT")
    # Reports occasionally restate a month; keep the latest submission
    return (
        out.sort(["period_id", "source_file"])
        .unique(subset=["TCPID", "year", "month"], keep="last")
        .drop(["Year", "Month"])
        .sort(["year", "month"])
    )


def _require_periods(frame: pl.DataFrame, label: str) -> None:
    actual = set(frame.get_column("period_id").unique().to_list())
    missing = [period for period in PERIODS if period not in actual]
    if missing:
        raise DataValidationError(f"{label} are missing reporting periods: {missing}")


def build_summary(
    complaints: pl.DataFrame,
    monthly: pl.DataFrame,
    locations: pl.DataFrame | None = None,
) -> pl.DataFrame:
    _require_periods(complaints, "Complaint data")
    _require_periods(monthly, "Month-Level data")

    optional_counts = [
        pl.when(pl.col(source).is_not_null().any())
        .then(pl.col(source).sum())
        .otherwise(None)
        .alias(alias)
        for alias, source in SUMMARY_OPTIONAL_COUNTS.items()
        if source in complaints.columns
    ]
    counts = complaints.group_by("period_id").agg(
        pl.col("ComplaintPUDO").sum().alias("pudo_complaints"),
        pl.when(pl.col("PUDOTravelLane").is_null().any())
        .then(None)
        .when(pl.col("PUDOTravelLane").is_not_null().any())
        .then(pl.col("PUDOTravelLane").sum())
        .otherwise(None)
        .alias("pudo_travel_lane"),
        pl.col("CollisionPUDOAny").sum().alias("pudo_collisions_incident_report"),
        pl.len().alias("retained_event_rows"),
        *optional_counts,
    )

    if locations is not None:
        modern_periods = [p for p in PERIODS if p.startswith(("2025", "2026"))]
        actual_location_periods = set(locations.get_column("period_id").unique())
        missing_modern = [p for p in modern_periods if p not in actual_location_periods]
        if missing_modern:
            raise DataValidationError(
                f"Incidents-Location data are missing modern periods: {missing_modern}"
            )
        location_counts = locations.group_by("period_id").agg(
            pl.col("CollisionsAll").sum().alias("collisions_all_location"),
            pl.col("CollisionsPUDO").sum().alias("pudo_collisions_location"),
            pl.when(pl.col("PUDOTravelLane").is_null().any())
            .then(None)
            .otherwise(pl.col("PUDOTravelLane").sum())
            .alias("pudo_travel_lane_location"),
            pl.len().alias("location_tract_rows"),
        )
        counts = counts.join(location_counts, on="period_id", how="left")
    else:
        counts = counts.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("collisions_all_location"),
            pl.lit(None, dtype=pl.Int64).alias("pudo_collisions_location"),
            pl.lit(None, dtype=pl.Int64).alias("pudo_travel_lane_location"),
            pl.lit(None, dtype=pl.UInt32).alias("location_tract_rows"),
        )

    counts = counts.with_columns(
        pl.when(
            (
                pl.col("period_id").str.starts_with("2025")
                | pl.col("period_id").str.starts_with("2026")
            )
            & pl.col("pudo_collisions_location").is_not_null()
        )
        .then(pl.col("pudo_collisions_location"))
        .otherwise(pl.col("pudo_collisions_incident_report"))
        .alias("pudo_collisions"),
        (
            pl.col("pudo_collisions_location")
            - pl.col("pudo_collisions_incident_report")
        ).alias("pudo_collision_reconciliation_gap"),
        pl.when(
            (
                pl.col("period_id").str.starts_with("2025")
                | pl.col("period_id").str.starts_with("2026")
            )
            & pl.col("pudo_collisions_location").is_not_null()
        )
        .then(pl.lit("Incidents-Location"))
        .otherwise(pl.lit("legacy Incidents-Complaints aggregate"))
        .alias("pudo_collision_primary_source"),
    )

    # Exposure: sum monthly VMT over the exact months each period covers
    month_map = pl.DataFrame(
        [
            {"period_id": pid, "year": y, "month": m}
            for pid, (_, months) in PERIODS.items()
            for (y, m) in months
        ]
    ).with_columns(pl.col("year").cast(pl.Int32), pl.col("month").cast(pl.Int8))
    exposure = (
        month_map.join(monthly, on=["year", "month"], how="left")
        .group_by("period_id")
        .agg(
            pl.col("vmt_total").sum().alias("vmt"),
            pl.col("TotalTrips").sum().alias("trips"),
            pl.col("vmt_total").count().alias("n_months"),
        )
    )

    # A period whose files are missing sums to 0.0, not null - make that
    # explicit so rates come out null instead of infinite.
    exposure = exposure.with_columns(
        pl.when(pl.col("vmt") > 0).then(pl.col("vmt")).otherwise(None).alias("vmt"),
        pl.when(pl.col("trips") > 0).then(pl.col("trips")).otherwise(None).alias("trips"),
    )

    expected_months = {period: len(months) for period, (_, months) in PERIODS.items()}
    observed_months = dict(
        exposure.select(["period_id", "n_months"]).iter_rows()
    )
    incomplete = {
        period: (observed_months.get(period, 0), expected)
        for period, expected in expected_months.items()
        if observed_months.get(period, 0) != expected
    }
    if incomplete:
        raise DataValidationError(
            f"Incomplete Month-Level coverage (observed, expected): {incomplete}"
        )

    meta = pl.DataFrame([_period_meta(p) for p in PERIODS])
    summary = (
        meta.join(counts, on="period_id", how="left")
        .join(exposure, on="period_id", how="left")
        .with_columns(
            (pl.col("pudo_complaints") / pl.col("vmt") * 100_000).alias(
                "pudo_per_100k_vmt"
            ),
            (pl.col("pudo_complaints") / pl.col("trips") * 100_000).alias(
                "pudo_per_100k_trips"
            ),
        )
        .sort("period_id")
    )
    critical = [
        "pudo_complaints",
        "pudo_collisions",
        "vmt",
        "trips",
        "pudo_per_100k_vmt",
        "pudo_per_100k_trips",
    ]
    null_counts = summary.select(
        [pl.col(c).null_count().alias(c) for c in critical]
    ).row(0)
    bad = {c: count for c, count in zip(critical, null_counts) if count}
    if bad:
        raise DataValidationError(f"Summary contains null critical values: {bad}")
    return summary
