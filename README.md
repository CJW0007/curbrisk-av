# CurbRisk AV

**Quantifying driverless pick-up and drop-off risk using real-world autonomous vehicle deployment data.**

CurbRisk AV evaluates **PUDO (pick-up/drop-off) risk for driverless vehicles** using Waymo deployment and complaint data reported to the California Public Utilities Commission (CPUC).

The project focuses on three fundamental questions in risk analysis:

1. **What are the hazards?**
   Identify potential sources of danger, harm, or loss associated with autonomous vehicle PUDO operations.

2. **What are the consequences?**
   Assess the potential severity and impact of those hazards.

3. **How likely are they?**
   Estimate the frequency of PUDO-related complaints using CPUC data from **2024 Q3 through 2026 Q2**, while controlling for vehicle exposure using **vehicle miles traveled (VMT)**.

## Analysis

The analysis follows the Fall 2026 class exercise: identify PUDO hazards,
assess their consequences, determine likelihood while controlling for miles
driven, and place the issue on a likelihood × consequence risk chart. It also
examines whether PUDO complaint risk is **increasing, decreasing, or remaining
stable over time**.

Rather than comparing raw complaint counts alone, complaint frequency is normalized by exposure:

$$
\text{PUDO Risk Rate} =
\frac{\text{PUDO Complaints}}{\text{Vehicle Miles Traveled}}
$$

Exposure-adjusted rates and statistical trend models are then used to evaluate changes across reporting periods and place PUDO hazards on a **likelihood × consequence risk matrix**.

The detailed Chinese review—covering the five original bugs, source-schema
audit, preprocessing decisions, feature/sample relationships, distribution,
trend models, and consequence analysis—is available in
[`docs/ANALYSIS_AND_FIXES_ZH.md`](docs/ANALYSIS_AND_FIXES_ZH.md).

The class prompt describes Q3 2024–Q2 2026 as eight quarters. CPUC actually
published nine usable windows because it issued a one-month December 2024
transition report before switching to calendar quarters in 2025. The primary
trend model retains all nine windows with their actual time spacing. The
Notebook combines Sep–Nov and Dec 2024 only for the requested four-block Y1
versus four-block Y2 classroom comparison, and labels that choice explicitly.

## Data

Public data comes from the **California Public Utilities Commission Autonomous Vehicle Program Quarterly Reports**.

The reproducible [`pudo-pipeline`](pudo-pipeline/) package downloads and processes the quarterly reports into analysis-ready Parquet datasets containing:

* PUDO complaints and incidents
* Tract-level collision aggregates and incident-row reconciliation
* Mutually exclusive highest-listed PUDO collision severity
* Quarterly and monthly vehicle activity
* Trips and vehicle miles traveled
* Exposure-adjusted PUDO complaint rates

## Repository Structure

```text
curbrisk-av/
├── docs/               # Review notes and analysis decisions
├── pudo-pipeline/
│   ├── src/            # CPUC ingestion, normalization, and validation
│   ├── notebooks/      # Risk and statistical analysis
│   ├── tests/          # Transformation and validation regression tests
│   └── data/           # Generated locally; ignored by Git
└── README.md
```

## Goal

The goal of CurbRisk AV is to move the discussion of driverless PUDO safety from **anecdotal reports to measurable risk**, combining hazard identification, consequence assessment, and exposure-adjusted likelihood estimation.
