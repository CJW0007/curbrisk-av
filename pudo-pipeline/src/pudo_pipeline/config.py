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
COLLISION_SEVERITY_FLAGS = [
    "CollisionSeverityPropertyDamage",
    "CollisionSeverityInjuryPossible",
    "CollisionSeverityInjuryMinor",
    "CollisionSeverityInjurySevere",
    "CollisionSeverityFatality",
]

# For 2025+ row-level files, collision severity can be linked to a PUDO
# collision on the same row.  The 2024 aggregate files do not preserve that
# linkage, so these derived fields remain null for legacy periods.
PUDO_SEVERITY_MAP = {
    "PUDOCollisionSeverityPropertyDamage": "CollisionSeverityPropertyDamage",
    "PUDOCollisionSeverityInjuryPossible": "CollisionSeverityInjuryPossible",
    "PUDOCollisionSeverityInjuryMinor": "CollisionSeverityInjuryMinor",
    "PUDOCollisionSeverityInjurySevere": "CollisionSeverityInjurySevere",
    "PUDOCollisionSeverityFatality": "CollisionSeverityFatality",
}

# Mutually exclusive, highest-observed-severity indicators.  The source
# severity flags are multi-label (for example, a minor injury can also carry
# ``InjuryPossible=Y``), so these columns are the safe ones to sum when a
# distribution of unique PUDO collision outcomes is needed.
PUDO_WORST_SEVERITY_COLUMNS = {
    "Property damage": "PUDOCollisionWorstPropertyDamage",
    "Possible injury": "PUDOCollisionWorstInjuryPossible",
    "Minor injury": "PUDOCollisionWorstInjuryMinor",
    "Severe injury": "PUDOCollisionWorstInjurySevere",
    "Fatality": "PUDOCollisionWorstFatality",
    "No listed severity flag": "PUDOCollisionWorstNoListedSeverity",
}

COMPLAINT_KEEP = (
    ["TCPID"] + COLLISION_PUDO_FLAGS + COLLISION_SEVERITY_FLAGS + COMPLAINT_FLAGS
)

# Before 2025, CPUC published one aggregate row per reporting period.  From
# 2025 onward the same concepts are represented as row-level Y/N flags.  Map
# the legacy aggregate columns to the canonical names used by the pipeline.
LEGACY_COUNT_MAP = {
    "ComplaintPUDO": "ComplaintsPUDO",
    "PUDOTravelLane": "PUDOTravelLaneAll",
    "CollisionPUDOAny": "CollisionsPUDOAll",
}

# Optional legacy totals that can be normalized without pretending that the
# 2024 aggregate row has 2025+'s event-level linkage.
LEGACY_OPTIONAL_COUNT_MAP = {
    "ComplaintSafety": "ComplaintsSafety",
    "ComplaintAccessibility": "ComplaintsAccessibility",
    "ComplaintWAV": "ComplaintsWAV",
    "ComplaintCustomerService": "ComplaintsCustomerService",
    "ComplaintOther": "ComplaintsOther",
    "CollisionPUDOPassenger": "CollisionsPUDOPassenger",
    "CollisionPUDOPedestrian": "CollisionsPUDOPedestrian",
    "CollisionPUDOBicycleScooter": "CollisionsPUDOBicycleScooter",
    "CollisionPUDOMotorcycles": "CollisionsPUDOMotorcycles",
    "CollisionPUDOOtherVehicle": "CollisionsPUDOOtherVehicle",
    "CollisionPUDORail": "CollisionsPUDORail",
    "CollisionPUDOProperty": "CollisionsPUDOProperty",
    "CollisionSeverityPropertyDamage": "CollisionSeverityPropertyDamage",
    "CollisionSeverityInjuryPossible": "CollisionSeverityInjuryPossible",
    "CollisionSeverityInjuryMinor": "CollisionSeverityInjuryMinor",
    "CollisionSeverityInjurySevere": "CollisionSeverityInjurySevere",
    "CollisionSeverityFatality": "CollisionSeverityFatality",
}

# Optional consequence-related totals written to pudo_summary.parquet.
SUMMARY_OPTIONAL_COUNTS = {
    "pudo_complaint_collision_overlap": "PUDOComplaintCollisionOverlap",
    "complaint_safety": "ComplaintSafety",
    "complaint_accessibility": "ComplaintAccessibility",
    "complaint_wav": "ComplaintWAV",
    "complaint_customer_service": "ComplaintCustomerService",
    "complaint_other": "ComplaintOther",
    "pudo_collision_passenger": "CollisionPUDOPassenger",
    "pudo_collision_pedestrian": "CollisionPUDOPedestrian",
    "pudo_collision_bicycle_scooter": "CollisionPUDOBicycleScooter",
    "pudo_collision_motorcycles": "CollisionPUDOMotorcycles",
    "pudo_collision_other_vehicle": "CollisionPUDOOtherVehicle",
    "pudo_collision_rail": "CollisionPUDORail",
    "pudo_collision_property": "CollisionPUDOProperty",
    "collision_severity_property_damage": "CollisionSeverityPropertyDamage",
    "collision_severity_injury_possible": "CollisionSeverityInjuryPossible",
    "collision_severity_injury_minor": "CollisionSeverityInjuryMinor",
    "collision_severity_injury_severe": "CollisionSeverityInjurySevere",
    "collision_severity_fatality": "CollisionSeverityFatality",
    "pudo_collision_severity_property_damage": "PUDOCollisionSeverityPropertyDamage",
    "pudo_collision_severity_injury_possible": "PUDOCollisionSeverityInjuryPossible",
    "pudo_collision_severity_injury_minor": "PUDOCollisionSeverityInjuryMinor",
    "pudo_collision_severity_injury_severe": "PUDOCollisionSeverityInjurySevere",
    "pudo_collision_severity_fatality": "PUDOCollisionSeverityFatality",
    "pudo_collision_severity_any_positive": "PUDOCollisionSeverityAnyPositive",
    "pudo_collision_severity_minor_or_worse": "PUDOCollisionSeverityMinorOrWorse",
    "pudo_collision_worst_property_damage": "PUDOCollisionWorstPropertyDamage",
    "pudo_collision_worst_injury_possible": "PUDOCollisionWorstInjuryPossible",
    "pudo_collision_worst_injury_minor": "PUDOCollisionWorstInjuryMinor",
    "pudo_collision_worst_injury_severe": "PUDOCollisionWorstInjurySevere",
    "pudo_collision_worst_fatality": "PUDOCollisionWorstFatality",
    "pudo_collision_worst_no_listed_severity": "PUDOCollisionWorstNoListedSeverity",
}

# Month_Level columns (denominator / activity)
MONTH_LEVEL_KEEP = [
    "TCPID",
    "Year",
    "Month",
    "TotalTrips",
    "TotalWaiting",
    "TotalVMTPeriod1",
    "TotalVMTPeriod2",
    "TotalVMTPeriod3",
    "TotalVMTZEV",
    "TotalPassengersCarried",
    "TotalPMT",
    "TotalWAVsAvail",
    "TotalWAVsRequested",
    "TotalWAVsDeclinedUnavail",
    "TotalWAVsFulfilled",
]
