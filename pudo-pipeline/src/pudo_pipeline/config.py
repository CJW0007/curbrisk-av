"""Configuration: source URLs, reporting-period map, paths, column selections.

CPUC reporting periods changed on 2025-01-01 from Sep-Nov style quarters to
calendar quarters. To cover the assignment window (2024 Q3 - 2026 Q2) we pull
the Jun-Aug 2024 and Sep-Nov 2024 reports plus the Dec 2024 one-month stub,
then the six calendar-quarter reports of 2025-2026.

Complaint rows have redacted timestamps, so a complaint can only be attributed
to the reporting period of the file it came from. VMT (Month_Level) has real
Year/Month columns, so exposure is summed over the exact months of each
period. Numerator and denominator therefore always cover identical windows.
"""

from pathlib import Path

CPUC_MEDIA = (
    "https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/"
    "consumer-protection-and-enforcement-division/documents/tlab/av-programs/"
)

# period_id -> (zip filename on CPUC site, [(year, month), ...] covered)
PERIODS: dict[str, tuple[str, list[tuple[int, int]]]] = {
    "2024P3_JunAug": (
        "av-deployment_jun_aug_2024_public.zip",
        [(2024, 6), (2024, 7), (2024, 8)],
    ),
    "2024P4_SepNov": (
        "waymo-dep-sep-nov-2024-public_2a.zip",
        [(2024, 9), (2024, 10), (2024, 11)],
    ),
    "2024P5_Dec": (
        "waymo-dep-dec-2024--public_2.zip",
        [(2024, 12)],
    ),
    "2025Q1": (
        "waymo-driverless-deployment-2025-q1.zip",
        [(2025, 1), (2025, 2), (2025, 3)],
    ),
    "2025Q2": ("waymo-deployment-2025q2.zip", [(2025, 4), (2025, 5), (2025, 6)]),
    "2025Q3": ("waymo-deployment-2025q3.zip", [(2025, 7), (2025, 8), (2025, 9)]),
    "2025Q4": ("waymo-deployment-2025q4.zip", [(2025, 10), (2025, 11), (2025, 12)]),
    "2026Q1": ("waymo-deployment-2026q1.zip", [(2026, 1), (2026, 2), (2026, 3)]),
    "2026Q2": ("waymo-deployment-2026q2.zip", [(2026, 4), (2026, 5), (2026, 6)]),
}

COMPANY = "Waymo"
# CPUC formats the permit as PSG0038152 in the quarterly CSV files.  The
# Jun-Aug 2024 archive contains multiple carriers, so the file/folder name is
# not sufficient to identify Waymo rows.
COMPANY_TCPIDS = {
    "PSG0038152",
    # Some CPUC Waymo Incidents-Complaints overflow parts transpose two
    # digits even though the archive and filename identify PSG0038152.
    "PSG0031852",
}

# Project-relative data layout (override with PUDO_DATA_DIR env var)
DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"          # downloaded zips
EXTRACT_DIR = DATA_DIR / "extracted"  # unzipped, one folder per period_id
OUT_DIR = DATA_DIR / "parquet"      # pipeline outputs

# Incidents-Complaints columns worth keeping (everything else is redacted or
# out of scope). Y/N flags parse to booleans downstream.
COMPLAINT_FLAGS = [
    "PUDOTravelLane",
    "ComplaintSafety",
    "ComplaintPUDO",
    "ComplaintAccessibility",
    "ComplaintWAV",
    "ComplaintCustomerService",
    "ComplaintOther",
]
COLLISION_PUDO_FLAGS = [
    "CollisionPUDOPassenger",
    "CollisionPUDOPedestrian",
    "CollisionPUDOBicycleScooter",
    "CollisionPUDOMotorcycles",
    "CollisionPUDOOtherVehicle",
    "CollisionPUDORail",
    "CollisionPUDOProperty",
]
COMPLAINT_KEEP = ["TCPID"] + COLLISION_PUDO_FLAGS + COMPLAINT_FLAGS

# Before 2025, CPUC published one aggregate row per reporting period.  From
# 2025 onward the same concepts are represented as row-level Y/N flags.  Map
# the legacy aggregate columns to the canonical names used by the pipeline.
LEGACY_COUNT_MAP = {
    "ComplaintPUDO": "ComplaintsPUDO",
    "PUDOTravelLane": "PUDOTravelLaneAll",
    "CollisionPUDOAny": "CollisionsPUDOAll",
}

# Month_Level columns (denominator / activity)
MONTH_LEVEL_KEEP = [
    "TCPID",
    "Year",
    "Month",
    "TotalTrips",
    "TotalVMTPeriod1",
    "TotalVMTPeriod2",
    "TotalVMTPeriod3",
    "TotalVMTZEV",
    "TotalPassengersCarried",
    "TotalPMT",
]
