# CurbRisk AV collaborator context

This repository analyzes Waymo pick-up/drop-off (PUDO) risk using public CPUC
AV Deployment reports. The goal is a reproducible course analysis, not an
individual-ride prediction system.

## Source-data facts that affect every analysis

- CPUC supplies nine real reporting windows: Jun-Aug 2024, Sep-Nov 2024, a
  December 2024 stub, and six calendar quarters from 2025 Q1 through 2026 Q2.
  Keep all nine windows in the audit table. Combine Sep-Nov and December only
  for the course's requested eight-block Y1/Y2 comparison.
- The 2024 complaint files are period-level aggregate tables. The 2025+ files
  are row-level event exports. Do not treat a fitted trend across that schema
  boundary as the primary risk result; the six 2025+ windows are the primary
  comparable-schema sample.
- Modern Incidents-Complaints archives contain 23,825,756 exact duplicate
  all-N/redacted template rows. They are not rides, incidents, controls, or
  negative samples. The loader stream-filters them and retains only relevant
  event rows.
- Waymo's CPUC identifier is `PSG0038152`; some Waymo overflow files contain
  the transposed published value `PSG0031852`. The 2024 archive also contains
  Cruise. Filter by permitted TCPID and driverless source path.
- Numeric fields may contain thousands separators, `$`, or `N/A`. Parsing must
  not silently convert a populated critical field to null or zero.
- Preserve three states for flags: `Y=True`, `N=False`, and redacted/blank/null
  as unknown. In particular, unknown travel-lane status is not zero.
- Use `Incidents-Location.CollisionsPUDO` for collision frequency and retain
  the incident actor-row count as a separate reconciliation field. The two
  differ in 2025 Q1 and 2026 Q2; the December 2024 aggregate source also
  conflicts with the location/hour totals.
- Collision actor and severity flags are multi-label. Collapse severity to one
  highest listed level per PUDO collision row when making a distribution.
  Modern data contain one severe-injury-coded PUDO collision and no
  fatality-coded PUDO collision. Zero observed fatalities is not zero future
  risk.

## Analysis structure

The project deliberately keeps four grains separate:

1. monthly operating exposure;
2. real CPUC reporting-window counts and rates;
3. relevant modern event rows for category/actor/severity cross-tabs;
4. tract/window location aggregates for collision reconciliation.

Use one exposure offset at a time. VMT is the course-requested primary offset;
trips are a PUDO-opportunity sensitivity. Trips and VMT are almost perfectly
correlated and should not be simultaneous predictors in the six-window model.

The primary trend conclusion comes from 2025+ comparable-schema models and
must report interval and p-value. The full mixed-schema history is descriptive
or sensitivity analysis only. Current evidence does not establish a rise or
fall in the modern complaint rate; collision rate has a downward point signal
but its conservative interval crosses zero.

Keep complaints, collisions, and injury-coded collisions as separate risk
scenarios. Do not assign one consequence label to the whole PUDO problem.

## Pipeline contract

`pudo-build` writes:

- `complaints.parquet`: legacy aggregate rows plus relevant modern event rows;
- `monthly_activity.parquet`: one row per month;
- `collision_locations.parquet`: tract/reporting-window aggregates;
- `pudo_summary.parquet`: one row per real reporting window.

The command must fail before printing `[done]` when periods/months are missing,
critical numeric values are unparseable, exposure is non-positive, or a required
risk rate is null. Run the regression tests and execute every notebook code
cell after changes.

See `docs/ANALYSIS_AND_FIXES.md` for the full analysis and
`docs/UPSTREAM_42A8AB0_REVIEW.md` for the comparison with Jonathan's 2026-08-30
update.
