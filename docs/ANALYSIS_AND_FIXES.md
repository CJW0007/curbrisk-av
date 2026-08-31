# Waymo PUDO Data Pipeline: Problems, Fixes, and Analysis

This document records the data audit, code corrections, statistical analysis,
and risk interpretation performed from Jonathan's original repository. The
changes were developed on the independent `fix/data-pipeline-validation`
branch so that each item can be reviewed separately.

## 1. The Five Original Problems

### 1.1 Thousands separators broke exposure parsing

CPUC reports trips and VMT in formats such as `1,818,206` and
`11,233,601.16`. The original code converted these strings directly to
numbers, causing comma-formatted values to become null.

Resolution:

- Remove thousands separators before numeric conversion.
- Strictly validate year, month, trips, P1/P2/P3 VMT, and total VMT.
- Stop immediately without calculating risk rates when critical exposure
  values cannot be parsed.

Verified 2025 Q1 values:

- trips: `1,818,206`;
- VMT: `11,233,601.16`.

### 1.2 The 2024 aggregate and 2025+ row-level schemas differ

Each 2024 file contains one row of reporting-period totals, whereas each
2025+ row contains published event flags. The pipeline now parses the two
schemas separately, maps them to common canonical columns, and preserves
`record_grain` as either:

- `period_aggregate`;
- `row_level`.

All nine real reporting windows remain available for description and
sensitivity analysis. The primary trend models use only the six
schema-consistent 2025+ windows.

### 1.3 The 2024 archive contains multiple carriers

Before aggregating complaint, monthly, or location data, the pipeline now:

- excludes Drivered directories;
- filters rows by Waymo TCPID;
- excludes Cruise and unknown TCPIDs;
- accepts the known transposed TCPID found in some CPUC Waymo overflow parts.

### 1.4 The CLI printed `[done]` even when every risk rate was null

The CLI now validates:

- all nine target reporting windows;
- expected month coverage in every period;
- positive trips and VMT;
- parseable critical numeric values;
- non-null primary counts and risk rates.

Any failed check prints `[error]` and returns a failure status. The CLI prints
the following message only after all validations pass:

```text
[done] validation passed; wrote 4 parquet files ...
```

### 1.5 The saved Notebook contained an error and unfinished analysis

The Notebook was reorganized into this sequence:

```text
data grain -> hazard -> consequence -> features/exposure -> distribution
-> likelihood model -> sensitivity -> scenario risk matrix -> limitations
```

Saved execution outputs were removed from the source Notebook. A clean kernel
successfully executed all 20 code cells against the validated real-data
summary with no errors.

## 2. Additional Problems Found During the Audit

### 2.1 The 23.8 million empty template rows are not samples

The official 2025+ archives contain `23,825,756` byte-for-byte duplicate
all-N/redacted template rows. The relevant statistical units are reporting
windows, not those filler rows:

| Data layer | n | Appropriate use |
|---|---:|---|
| Month-Level | 25 months | Exposure and operational-composition description |
| CPUC windows | 9 | Transparent full-window description and sensitivity |
| 2025+ comparable windows | 6 | Primary trend models |
| 2025+ non-filler source rows | 11,608 | Source/event audit |
| Modern analytic rows retained by the pipeline | 2,821 | Complaint, PUDO actor, and severity cross-tabs |

The loader now uses column projection and streaming positive-event filters.
A 263,000,996-byte template-only shard retained zero rows in a direct test.
The original ZIP remains the audit record; simple `drop_duplicates` must not
be used on genuine event records.

### 2.2 Redacted does not mean false

Flags are mapped as follows:

- `Y -> True/1`;
- `N -> False/0`;
- `Redacted/NULL/blank -> null`.

Every public location value for `PUDOTravelLane` is redacted. The correct
conclusion is "not estimable," not zero.

### 2.3 Collision frequency and actor rows serve different purposes

`Incidents-Location.CollisionsPUDO` is a direct collision aggregate. Incident
actor flags support actor/severity linkage but can miss events whose subtype
is not published.

The 2025+ reconciliation is:

| Period | Location | Actor-row OR | Gap |
|---|---:|---:|---:|
| 2025 Q1 | 34 | 33 | 1 |
| 2025 Q2 | 54 | 54 | 0 |
| 2025 Q3 | 46 | 46 | 0 |
| 2025 Q4 | 50 | 50 | 0 |
| 2026 Q1 | 69 | 69 | 0 |
| 2026 Q2 | 65 | 63 | 2 |

December 2024 also contains a source conflict: the complaint aggregate says
zero, while the Location table and PUDO hour-level field support eight.
Collision frequency therefore uses Location totals whenever available while
retaining the incident/aggregate count and reconciliation gap.

### 2.4 Severity flags are multi-label

A Minor record can also have Possible=`Y`, so the five severity columns must
not be added directly. For each PUDO collision row, the pipeline creates one
mutually exclusive highest-listed severity using:

```text
Fatal > Severe > Minor > Possible > Property > No listed severity flag
```

Among 315 actor-linked PUDO collision rows in 2025+:

- No listed severity flag: 292;
- Property damage: 2;
- Possible injury: 9;
- Minor injury: 11;
- Severe injury: 1;
- Fatality: 0.

`No listed severity flag` does not mean "no harm," and zero fatality-coded
PUDO rows do not imply zero future fatality risk.

## 3. Features and Samples

Most operating variables are jointly driven by service expansion:

- month index vs. trips: `r=0.9750`;
- month index vs. VMT: `r=0.9744`;
- trips vs. VMT: `r=0.9987`;
- the P1 share decreases over time;
- the P3 share increases over time.

The models therefore use only:

- `time_months` as the primary predictor;
- `log(VMT)` as the primary exposure offset;
- `log(trips)` as a PUDO-opportunity sensitivity offset.

VMT, trips, passengers, PMT, and time are not entered together in a model
with only six windows, and a rate is not used to predict its own count.
`TotalVMTZEV` duplicates P1+P2+P3, while the four monthly Waymo driverless WAV
fields have zero variance; none are model inputs.

## 4. Distributions and Statistical Results

The full nine-window complaint/VMT rate is strongly right-skewed. Its highest
values occur in 2024, at the same time as the level/schema discontinuity:

- mean: `0.3765 / 100k VMT`;
- median: `0.2807`;
- CV: `0.6006`;
- skew: `2.3388`.

The six 2025+ windows form a much narrower distribution:

- complaint/VMT mean: `0.2672`, CV: `0.0905`;
- complaint/trips mean: `1.7222`, CV: `0.0937`;
- collision/VMT CV: `0.2420`.

These observations form a short time series, not independent and identically
distributed draws. The Notebook therefore uses time dots, exact Poisson rate
intervals, and ECDFs rather than relying on histograms or normality tests.

Primary Poisson offset results:

| Outcome | Offset | Annual change | 95% CI | p |
|---|---|---:|---:|---:|
| PUDO complaint | VMT | +3.7% | -21.0% to +36.2% | 0.792 |
| PUDO complaint | trips | +12.3% | -14.4% to +47.3% | 0.404 |
| PUDO collision | VMT | -28.2% | -50.4% to +4.1% | 0.080 |
| PUDO collision | trips | -22.1% | -45.1% to +10.7% | 0.163 |

The complaint rate does not provide enough evidence to establish an increase
or decrease. The collision rate shows a downward signal, but its interval
still crosses zero. A declining full nine-window result is confounded by the
schema change and is reported only as a sensitivity analysis.

## 5. Consequences Must Be Scenario-Specific

Total 2025+ exposure is `18,603,660 trips` and `121,205,767 VMT`.

| Outcome | Count | /100k trips | /million VMT |
|---|---:|---:|---:|
| PUDO complaint | 325 | 1.7470 | 2.6814 |
| Location PUDO collision | 318 | 1.7093 | 2.6236 |
| Collision with positive severity flag | 23 | 0.1236 | 0.1898 |
| Minor-or-worse collision | 12 | 0.0645 | 0.0990 |
| Severe collision | 1 | 0.0054 | 0.0083 |
| Fatality-coded collision | 0 | 0 | 0 |

PUDO complaint rows do not overlap PUDO collision rows in this extract, so
complaints cannot be used as a proxy for physical harm. The provisional risk
register separates:

1. a complaint/service signal;
2. a possible/minor-injury collision;
3. a severe-injury collision.

The lecture does not provide numeric likelihood cutoffs. The Notebook's
current generic 5-by-5 matrix, rate bins, and consequence mappings are
explicitly project-defined and provisional. The class prompt's reference to
the "previous slide" appears to point instead to the DOD 8-by-5 matrix. The
team should confirm the intended matrix, likelihood unit and thresholds, and
observed-versus-credible-worst-case consequence rule with the instructor.

## 6. Generated Data and Validation

Pipeline outputs:

| File | Grain |
|---|---|
| `complaints.parquet` | legacy aggregate / modern relevant event |
| `monthly_activity.parquet` | month |
| `collision_locations.parquet` | tract x reporting window |
| `pudo_summary.parquet` | reporting window |

Validation completed:

- 14/14 automated tests passed, including conflicting duplicate reports for
  the same tract;
- the end-to-end CLI build passed;
- all 20 Notebook code cells executed successfully;
- Python compilation, Notebook validation, and `git diff --check` passed.

## 7. Reproduction

```bash
cd pudo-pipeline
pip install -e .
pudo-build
jupyter lab notebooks/pudo_analysis.ipynb
python -m unittest discover -s tests -v
```

If the team later adopts formal likelihood/consequence thresholds, only the
Notebook's scenario rubric must change. The underlying numerator, exposure,
and severity hierarchy do not need to be redefined.

## 8. Integration Review of Jonathan's Latest Commit `42a8ab0`

Jonathan's `main` was fetched and compared file by file on 2026-08-30. That
commit correctly identified comma-formatted numbers, the 2024/2025 schema
split, Waymo TCPID variants, 2026 filenames, and exposure offsets. It could
not safely replace this branch as a whole because:

- it described approximately `23,825,756` all-N/redacted template duplicate
  rows as rides and used them for a statistically meaningless
  `per-million-rides` denominator;
- its headline negative-binomial model mixed the 2024 aggregate schema with
  the 2025+ row-level schema, so it could not distinguish a time trend from a
  schema level shift;
- its collision count still used actor flags/legacy aggregates and therefore
  missed eight December 2024, one 2025 Q1, and two 2026 Q2 Location collisions;
- its Notebook did not load severity but claimed there were no severe PUDO
  collisions; the modern data contain one severe-injury-coded PUDO collision;
- it could still write results and display `[done]` when a quarter or month
  was missing, and it added no regression tests.

The branch therefore used a semantic merge: it manually incorporated the
safe `N/A`/`$` cleaning, eight-block course-display explanation, and
collaboration documentation while retaining this branch's streaming filters,
fail-fast validation, nine real windows, six modern primary windows, Location
reconciliation, and consequence pipeline. See
[`UPSTREAM_42A8AB0_REVIEW.md`](UPSTREAM_42A8AB0_REVIEW.md) for the detailed
English comparison.
