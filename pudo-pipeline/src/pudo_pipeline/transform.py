"""Stage 2: parse extracted CSVs into tidy Polars frames.

Outputs
-------
complaints    one row per reported incident, Y/N flags as booleans,
              tagged with period_id / year / quarter / company.
monthly       one row per (year, month) of fleet activity (trips, VMT, PMT).
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
* Columns that are entirely "Redacted" or NULL are dropped; per-row
  "Redacted" strings in kept columns become nulls.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from .config import (
    COMPANY,
    COMPANY_TCPIDS,
    COMPLAINT_FLAGS,
    COLLISION_PUDO_FLAGS,
    LEGACY_COUNT_MAP,
    MONTH_LEVEL_KEEP,
    PERIODS,
)


class DataValidationError(ValueError):
    """Raised when source data are present but cannot support valid rates."""


def _read_csv_str(path: Path) -> pl.DataFrame:
    """Read everything as strings; normalize 'Redacted'/'NULL' to null."""
    df = pl.read_csv(path, infer_schema_length=0, ignore_errors=True)
    return df.with_columns(
        pl.all()
        .str.strip_chars()
        .replace(["Redacted", "REDACTED", "NULL", "null", ""], None)
    )


def _flag_to_bool(col: str) -> pl.Expr:
    return (pl.col(col) == "Y").fill_null(False).alias(col)


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
        c for c in COMPLAINT_FLAGS + COLLISION_PUDO_FLAGS if c in df.columns
    ]
    out = df.select(["TCPID"] + kept_flags).with_columns(
        [_flag_to_bool(c) for c in kept_flags]
    )
    out = out.with_columns(
        pl.any_horizontal(collision_cols).alias("CollisionPUDOAny")
    ).with_columns(
        [
            pl.col(c).cast(pl.Int64)
            for c in kept_flags + ["CollisionPUDOAny"]
        ]
    )
    return out.with_columns(_metadata_columns(period_id, source, "row_level"))


def _canonical_legacy(df: pl.DataFrame, period_id: str, source: Path) -> pl.DataFrame:
    missing = sorted(set(LEGACY_COUNT_MAP.values()) - set(df.columns))
    if missing:
        raise DataValidationError(f"{source} is missing legacy aggregate columns: {missing}")

    expressions = [
        _numeric_expr(old, pl.Int64).alias(canonical)
        for canonical, old in LEGACY_COUNT_MAP.items()
    ]
    out = df.select(["TCPID"] + list(LEGACY_COUNT_MAP.values())).with_columns(
        expressions
    ).select(["TCPID"] + list(LEGACY_COUNT_MAP))
    # Some legacy reports redact travel-lane totals.  Preserve that as null;
    # it is not equivalent to a reported zero.  Complaint and collision totals
    # are required for the primary analysis.
    critical = ["ComplaintPUDO", "CollisionPUDOAny"]
    if out.select(pl.any_horizontal([pl.col(c).is_null() for c in critical])).item():
        raise DataValidationError(f"{source} contains unparseable legacy PUDO counts")
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
            df = _waymo_rows(_read_csv_str(f), f)
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
            df = _waymo_rows(_read_csv_str(f), f)
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


def build_summary(complaints: pl.DataFrame, monthly: pl.DataFrame) -> pl.DataFrame:
    _require_periods(complaints, "Complaint data")
    _require_periods(monthly, "Month-Level data")

    counts = complaints.group_by("period_id").agg(
        pl.col("ComplaintPUDO").sum().alias("pudo_complaints"),
        pl.when(pl.col("PUDOTravelLane").is_not_null().any())
        .then(pl.col("PUDOTravelLane").sum())
        .otherwise(None)
        .alias("pudo_travel_lane"),
        pl.col("CollisionPUDOAny").sum().alias("pudo_collisions"),
        pl.len().alias("total_incident_rows"),
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
