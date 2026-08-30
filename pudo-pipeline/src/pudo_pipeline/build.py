"""Stage 3 / CLI: run the full pipeline and write parquet outputs.

Usage:
    pudo-build                 # download + extract + transform + write
    pudo-build --no-download   # use already-extracted data in data/extracted/
    PUDO_DATA_DIR=/some/path pudo-build   # relocate the data directory
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import config
from .download import download_all, extract_all
from .transform import (
    DataValidationError,
    build_summary,
    load_collision_locations,
    load_complaints,
    load_monthly,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PUDO parquet datasets")
    parser.add_argument("--no-download", action="store_true",
                        help="skip network; use existing data/extracted/")
    args = parser.parse_args()

    data_dir = Path(os.environ.get("PUDO_DATA_DIR", config.DATA_DIR))
    raw = data_dir / "raw"
    extracted = data_dir / "extracted"
    out = data_dir / "parquet"
    out.mkdir(parents=True, exist_ok=True)

    if not args.no_download:
        download_all(raw)
        extract_all(raw, extracted)

    try:
        complaints = load_complaints(extracted)
        monthly = load_monthly(extracted)
        locations = load_collision_locations(extracted)
        summary = build_summary(complaints, monthly, locations)
    except (DataValidationError, FileNotFoundError) as exc:
        parser.exit(2, f"[error] data validation failed: {exc}\n")

    complaints.write_parquet(out / "complaints.parquet")
    monthly.write_parquet(out / "monthly_activity.parquet")
    locations.write_parquet(out / "collision_locations.parquet")
    summary.write_parquet(out / "pudo_summary.parquet")

    print(f"\n[done] validation passed; wrote 4 parquet files to {out}/")
    print(summary)


if __name__ == "__main__":
    main()
