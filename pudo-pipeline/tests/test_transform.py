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
    load_collision_locations,
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
    def test_monthly_numbers_with_commas_and_currency_symbol(self) -> None:
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
                    (1, "550,457", "$1,430,498.32", "416,489.71", "1,634,709.90"),
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
                "ComplaintsSafety",
                "PUDOTravelLaneAll",
                "CollisionsPUDOAll",
                "CollisionSeverityInjurySevere",
            ]
            write_csv(
                root / "2024P4_SepNov" / "Waymo_Incidents-Complaints_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "ComplaintsPUDO": "40",
                        "ComplaintsSafety": "102",
                        "PUDOTravelLaneAll": "Redacted",
                        "CollisionsPUDOAll": "22",
                        "CollisionSeverityInjurySevere": "0",
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
                        "ComplaintsSafety": "999",
                        "PUDOTravelLaneAll": "999",
                        "CollisionsPUDOAll": "999",
                        "CollisionSeverityInjurySevere": "999",
                    }
                ],
            )

            complaints = load_complaints(root)
            self.assertEqual(complaints.height, 1)
            row = complaints.select(
                "ComplaintPUDO",
                "PUDOTravelLane",
                "CollisionPUDOAny",
                "ComplaintSafety",
                "CollisionSeverityInjurySevere",
                "PUDOCollisionSeverityInjurySevere",
                "record_grain",
            ).row(0)
            self.assertEqual(
                row,
                (40, None, 22, 102, 0, None, "period_aggregate"),
            )

    def test_waymo_filter_and_published_tcpid_typo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "PUDOTravelLane",
                "ComplaintPUDO",
                "CollisionPUDOPassenger",
                "CollisionSeverityInjurySevere",
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
                        "CollisionSeverityInjurySevere": "Y",
                    },
                    {
                        "TCPID": "PSG0031852",
                        "PUDOTravelLane": "N",
                        "ComplaintPUDO": "N",
                        "CollisionPUDOPassenger": "Y",
                        "CollisionSeverityInjurySevere": "Y",
                    },
                    {
                        "TCPID": "PSG0099999",
                        "PUDOTravelLane": "N",
                        "ComplaintPUDO": "Y",
                        "CollisionPUDOPassenger": "Y",
                        "CollisionSeverityInjurySevere": "Y",
                    },
                ],
            )

            complaints = load_complaints(root)
            totals = complaints.select(
                pl.len(),
                pl.col("ComplaintPUDO").sum(),
                pl.col("CollisionPUDOAny").sum(),
                pl.col("CollisionSeverityInjurySevere").sum(),
                pl.col("PUDOCollisionSeverityInjurySevere").sum(),
                pl.col("PUDOComplaintCollisionOverlap").sum(),
            ).row(0)
            # The non-PUDO severe row is retained as an all-collision severity
            # signal, but only the row with a PUDO collision contributes to
            # the PUDO-specific severe consequence count.
            self.assertEqual(totals, (2, 1, 1, 2, 1, 0))

    def test_redacted_flags_stay_null_and_all_n_templates_are_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "PUDOTravelLane",
                "ComplaintPUDO",
                "CollisionPUDOOtherVehicle",
                "CollisionSeverityInjuryPossible",
            ]
            write_csv(
                root / "2025Q1" / "Waymo_Incidents_Complaints_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "PUDOTravelLane": "Redacted",
                        "ComplaintPUDO": "N",
                        "CollisionPUDOOtherVehicle": "N",
                        "CollisionSeverityInjuryPossible": "N",
                    },
                    {
                        "TCPID": "PSG0038152",
                        "PUDOTravelLane": "Redacted",
                        "ComplaintPUDO": "Y",
                        "CollisionPUDOOtherVehicle": "N",
                        "CollisionSeverityInjuryPossible": "N",
                    },
                ],
            )

            complaints = load_complaints(root)
            self.assertEqual(complaints.height, 1)
            self.assertIsNone(complaints.select("PUDOTravelLane").item())
            self.assertEqual(complaints.select("ComplaintPUDO").item(), 1)

    def test_location_aggregate_is_primary_for_modern_collision_frequency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "Year",
                "Quarter",
                "Tract",
                "CollisionsAll",
                "CollisionsPUDO",
                "PUDOTravelLane",
            ]
            write_csv(
                root
                / "2025Q1"
                / "Driverless"
                / "Waymo_AV_Incidents-Location_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "Year": "2025",
                        "Quarter": "1",
                        "Tract": "1",
                        "CollisionsAll": "20",
                        "CollisionsPUDO": "34",
                        "PUDOTravelLane": "Redacted",
                    }
                ],
            )
            locations = load_collision_locations(root)
            self.assertEqual(locations.select("CollisionsPUDO").item(), 34)
            self.assertIsNone(locations.select("PUDOTravelLane").item())

    def test_conflicting_location_revisions_fail_instead_of_double_counting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "Year",
                "Quarter",
                "Tract",
                "CollisionsAll",
                "CollisionsPUDO",
                "PUDOTravelLane",
            ]
            rows = [
                {
                    "TCPID": "PSG0038152",
                    "Year": "2025",
                    "Quarter": "1",
                    "Tract": "1",
                    "CollisionsAll": "20",
                    "CollisionsPUDO": count,
                    "PUDOTravelLane": "Redacted",
                }
                for count in ["34", "35"]
            ]
            write_csv(
                root / "2025Q1" / "Waymo_AV_Incidents-Location_Part0.csv",
                fields,
                rows,
            )
            with self.assertRaisesRegex(DataValidationError, "Conflicting"):
                load_collision_locations(root)

    def test_worst_severity_is_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "PUDOTravelLane",
                "ComplaintPUDO",
                "CollisionPUDOPassenger",
                "CollisionSeverityInjuryPossible",
                "CollisionSeverityInjuryMinor",
                "CollisionSeverityInjurySevere",
            ]
            write_csv(
                root / "2026Q2" / "Waymo_Incidents_Complaints_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "PUDOTravelLane": "Redacted",
                        "ComplaintPUDO": "N",
                        "CollisionPUDOPassenger": "Y",
                        "CollisionSeverityInjuryPossible": "Y",
                        "CollisionSeverityInjuryMinor": "N",
                        "CollisionSeverityInjurySevere": "Y",
                    }
                ],
            )
            complaints = load_complaints(root)
            row = complaints.select(
                "PUDOCollisionWorstSeverity",
                "PUDOCollisionWorstInjuryPossible",
                "PUDOCollisionWorstInjurySevere",
                "PUDOCollisionSeverityAnyPositive",
                "PUDOCollisionSeverityMinorOrWorse",
            ).row(0)
            self.assertEqual(row, ("Severe injury", 0, 1, 1, 1))

    def test_non_pudo_severity_does_not_count_as_pudo_consequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [
                "TCPID",
                "PUDOTravelLane",
                "ComplaintPUDO",
                "CollisionPUDOPassenger",
                "CollisionSeverityInjurySevere",
            ]
            write_csv(
                root / "2025Q1" / "Waymo_Incidents_Complaints_Part0.csv",
                fields,
                [
                    {
                        "TCPID": "PSG0038152",
                        "PUDOTravelLane": "Redacted",
                        "ComplaintPUDO": "N",
                        "CollisionPUDOPassenger": "N",
                        "CollisionSeverityInjurySevere": "Y",
                    }
                ],
            )
            complaints = load_complaints(root)
            self.assertEqual(
                complaints.select("PUDOCollisionSeverityAnyPositive").item(), 0
            )
            self.assertIsNone(
                complaints.select("PUDOCollisionWorstSeverity").item()
            )

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

    def test_summary_prefers_location_collisions_when_available(self) -> None:
        complaints = pl.DataFrame(
            {
                "period_id": list(PERIODS),
                "ComplaintPUDO": [1] * len(PERIODS),
                "PUDOTravelLane": [None] * len(PERIODS),
                "CollisionPUDOAny": [3] * len(PERIODS),
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
        location_periods = [
            "2024P5_Dec",
            *[
                period
                for period in PERIODS
                if period.startswith(("2025", "2026"))
            ],
        ]
        locations = pl.DataFrame(
            {
                "period_id": location_periods,
                "CollisionsAll": [10] * len(location_periods),
                "CollisionsPUDO": [8] + [5] * (len(location_periods) - 1),
                "PUDOTravelLane": [None] * len(location_periods),
            }
        )

        summary = build_summary(
            complaints,
            pl.DataFrame(monthly_rows),
            locations,
        )
        modern = summary.filter(pl.col("period_id") == "2025Q1")
        legacy_discrepancy = summary.filter(pl.col("period_id") == "2024P5_Dec")
        legacy = summary.filter(pl.col("period_id") == "2024P3_JunAug")
        self.assertEqual(modern.select("pudo_collisions").item(), 5)
        self.assertEqual(
            modern.select("pudo_collision_reconciliation_gap").item(), 2
        )
        self.assertEqual(
            modern.select("pudo_collision_primary_source").item(),
            "Incidents-Location",
        )
        self.assertEqual(legacy_discrepancy.select("pudo_collisions").item(), 8)
        self.assertEqual(
            legacy_discrepancy.select("pudo_collision_reconciliation_gap").item(),
            5,
        )
        self.assertEqual(
            legacy_discrepancy.select("pudo_collision_primary_source").item(),
            "Incidents-Location",
        )
        self.assertEqual(legacy.select("pudo_collisions").item(), 3)

    def test_summary_rejects_empty_risk_rates(self) -> None:
        complaints = pl.DataFrame(
            {
                "period_id": list(PERIODS),
                "ComplaintPUDO": [1] * len(PERIODS),
                "PUDOTravelLane": [None] * len(PERIODS),
                "CollisionPUDOAny": [0] * len(PERIODS),
            }
        )
        monthly_rows = [
            {
                "period_id": period,
                "year": year,
                "month": month,
                "vmt_total": 0.0,
                "TotalTrips": 0.0,
            }
            for period, (_, months) in PERIODS.items()
            for year, month in months
        ]
        with self.assertRaisesRegex(DataValidationError, "null critical values"):
            build_summary(complaints, pl.DataFrame(monthly_rows))


if __name__ == "__main__":
    unittest.main()
