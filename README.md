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

The analysis examines whether PUDO complaint risk is **increasing, decreasing, or remaining stable over time**.

Rather than comparing raw complaint counts alone, complaint frequency is normalized by exposure:

$$
\text{PUDO Risk Rate} =
\frac{\text{PUDO Complaints}}{\text{Vehicle Miles Traveled}}
$$

Exposure-adjusted rates and statistical trend models are then used to evaluate changes across reporting periods and place PUDO hazards on a **likelihood × consequence risk matrix**.

## Data

Public data comes from the **California Public Utilities Commission Autonomous Vehicle Program Quarterly Reports**.

The reproducible [`pudo-pipeline`](pudo-pipeline/) package downloads and processes the quarterly reports into analysis-ready Parquet datasets containing:

* PUDO complaints and incidents
* Quarterly and monthly vehicle activity
* Trips and vehicle miles traveled
* Exposure-adjusted PUDO complaint rates

## Repository Structure

```text
curbrisk-av/
├── pudo-pipeline/
│   ├── src/            # CPUC ingestion, normalization, and validation
│   ├── notebooks/      # Risk and statistical analysis
│   ├── tests/          # Transformation and validation regression tests
│   └── data/           # Generated locally; ignored by Git
└── README.md
```

## Goal

The goal of CurbRisk AV is to move the discussion of driverless PUDO safety from **anecdotal reports to measurable risk**, combining hazard identification, consequence assessment, and exposure-adjusted likelihood estimation.
