from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import polars as pl

from pudo_pipeline.config import PERIODS
from pudo_pipeline.transform import (
    DataValidationError,
    build_summary,
    load_complaints,
    load_monthly,
)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TransformTests(unittest.TestCase):
    def test_monthly_numbers_with_commas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "Year",
                "Month",
                "TotalTrips",
                "TotalVMTPeriod1",
                "TotalVMTPeriod2",
                "TotalVMTPeriod3",
            ]
            rows = [
                {
                    "TCPID": "PSG0038152",
                    "Year": "2025",
                    "Month": str(month),
                    "TotalTrips": trips,
                    "TotalVMTPeriod1": p1,
                    "TotalVMTPeriod2": p2,
                    "TotalVMTPeriod3": p3,
                }
                for month, trips, p1, p2, p3 in [
                    (1, "550,457", "1,430,498.32", "416,489.71", "1,634,709.90"),
                    (2, "559,569", "1,326,808.24", "418,558.69", "1,740,554.80"),
                    (3, "708,180", "1,466,872.84", "541,715.75", "2,257,392.91"),
                ]
            ]
            write_csv(
                root / "2025Q1" / "Waymo_AV_Month-Level_Part0.csv",
                fields,
                rows,
            )

            monthly = load_monthly(root)
            totals = monthly.select(
                pl.col("TotalTrips").sum(), pl.col("vmt_total").sum()
            ).row(0)
            self.assertEqual(totals[0], 1_818_206)
            self.assertAlmostEqual(totals[1], 11_233_601.16, places=2)

    def test_invalid_monthly_number_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "Year",
                "Month",
                "TotalTrips",
                "TotalVMTPeriod1",
                "TotalVMTPeriod2",
                "TotalVMTPeriod3",
            ]
            write_csv(
                root / "2025Q1" / "Waymo_AV_Month-Level_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "Year": "2025",
                        "Month": "1",
                        "TotalTrips": "not-a-number",
                        "TotalVMTPeriod1": "1",
                        "TotalVMTPeriod2": "2",
                        "TotalVMTPeriod3": "3",
                    }
                ],
            )
            with self.assertRaisesRegex(DataValidationError, "Unparseable"):
                load_monthly(root)

    def test_2026_month_part_name_is_loaded_but_monthly_tract_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "Year",
                "Month",
                "TotalTrips",
                "TotalVMTPeriod1",
                "TotalVMTPeriod2",
                "TotalVMTPeriod3",
            ]
            row = {
                "TCPID": "PSG0038152",
                "Year": "2026",
                "Month": "1",
                "TotalTrips": "1,322,645",
                "TotalVMTPeriod1": "2,893,676.94",
                "TotalVMTPeriod2": "1,194,296.95",
                "TotalVMTPeriod3": "5,004,765.46",
            }
            write_csv(
                root / "2026Q1" / "Driverless" / "Waymo_AV_Month_Part0.csv",
                fields,
                [row],
            )
            tract_row = dict(row, TotalTrips="999,999,999")
            write_csv(
                root / "2026Q1" / "Driverless" / "Waymo_AV_Monthly_Tract_Part0.csv",
                fields,
                [tract_row],
            )

            monthly = load_monthly(root)
            self.assertEqual(monthly.height, 1)
            self.assertEqual(monthly.select("TotalTrips").item(), 1_322_645)

    def test_legacy_aggregate_schema_is_mapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "ComplaintsPUDO",
                "PUDOTravelLaneAll",
                "CollisionsPUDOAll",
            ]
            write_csv(
                root / "2024P4_SepNov" / "Waymo_Incidents-Complaints_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "ComplaintsPUDO": "40",
                        "PUDOTravelLaneAll": "Redacted",
                        "CollisionsPUDOAll": "22",
                    }
                ],
            )
            write_csv(
                root / "2024P4_SepNov" / "Cruise_Incidents_Complaints_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0039080",
                        "ComplaintsPUDO": "999",
                        "PUDOTravelLaneAll": "999",
                        "CollisionsPUDOAll": "999",
                    }
                ],
            )

            complaints = load_complaints(root)
            self.assertEqual(complaints.height, 1)
            row = complaints.select(
                "ComplaintPUDO",
                "PUDOTravelLane",
                "CollisionPUDOAny",
                "record_grain",
            ).row(0)
            self.assertEqual(row, (40, None, 22, "period_aggregate"))

    def test_waymo_filter_and_published_tcpid_typo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "PUDOTravelLane",
                "ComplaintPUDO",
                "CollisionPUDOPassenger",
            ]
            write_csv(
                root / "2025Q1" / "Waymo_Incidents_Complaints_Part1.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "PUDOTravelLane": "N",
                        "ComplaintPUDO": "Y",
                        "CollisionPUDOPassenger": "N",
                    },
                    {
                        "TCPID": "PSG0031852",
                        "PUDOTravelLane": "N",
                        "ComplaintPUDO": "N",
                        "CollisionPUDOPassenger": "Y",
                    },
                    {
                        "TCPID": "PSG0099999",
                        "PUDOTravelLane": "N",
                        "ComplaintPUDO": "Y",
                        "CollisionPUDOPassenger": "Y",
                    },
                ],
            )

            complaints = load_complaints(root)
            totals = complaints.select(
                pl.len(),
                pl.col("ComplaintPUDO").sum(),
                pl.col("CollisionPUDOAny").sum(),
            ).row(0)
            self.assertEqual(totals, (2, 1, 1))

    def test_summary_requires_every_reporting_period(self) -> None:
        complaints = pl.DataFrame(
            {
                "period_id": ["2025Q1"],
                "ComplaintPUDO": [1],
                "PUDOTravelLane": [0],
                "CollisionPUDOAny": [0],
            }
        )
        monthly = pl.DataFrame(
            {
                "period_id": ["2025Q1"],
                "year": [2025],
                "month": [1],
                "vmt_total": [1000.0],
                "TotalTrips": [100.0],
            }
        )
        with self.assertRaisesRegex(DataValidationError, "missing reporting periods"):
            build_summary(complaints, monthly)

    def test_complete_summary_has_valid_rates(self) -> None:
        complaints = pl.DataFrame(
            {
                "period_id": list(PERIODS),
                "ComplaintPUDO": [1] * len(PERIODS),
                "PUDOTravelLane": [0] * len(PERIODS),
                "CollisionPUDOAny": [0] * len(PERIODS),
            }
        )
        monthly_rows = [
            {
                "period_id": period,
                "year": year,
                "month": month,
                "vmt_total": 1000.0,
                "TotalTrips": 100.0,
            }
            for period, (_, months) in PERIODS.items()
            for year, month in months
        ]
        summary = build_summary(complaints, pl.DataFrame(monthly_rows))

        self.assertEqual(summary.height, len(PERIODS))
        self.assertEqual(summary.get_column("time_months").is_sorted(), True)
        self.assertEqual(
            summary.filter(pl.col("period_id") == "2024P5_Dec")
            .select("period_midpoint")
            .item(),
            "2024-12-16",
        )
        self.assertEqual(
            summary.select(pl.col("pudo_per_100k_vmt").null_count()).item(), 0
        )
        dec_rate = summary.filter(pl.col("period_id") == "2024P5_Dec").select(
            "pudo_per_100k_vmt"
        ).item()
        self.assertEqual(dec_rate, 100.0)


if __name__ == "__main__":
    unittest.main()
