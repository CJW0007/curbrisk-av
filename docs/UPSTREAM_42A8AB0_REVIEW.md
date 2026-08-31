# Review of upstream update `42a8ab0`

Reviewed on 2026-08-30 against branch `fix/data-pipeline-validation`.

Jonathan's update moves in the right direction: it recognizes comma-formatted
exposure, the two complaint schemas, Waymo's TCPID variants, CPUC filename
drift, exposure-offset trend models, and the course's eight-block presentation.
Those are all useful shared conclusions.

## What was integrated

- explicit normalization of `N/A` and `$` in numeric ingestion;
- corrected collaborator documentation explaining the nine real source windows
  versus the eight course comparison blocks;
- retention of VMT-offset modeling, overdispersion checks, and sensitivity
  analysis, with the comparable 2025+ schema kept as the primary sample;
- Jonathan's latest upstream commit recorded in the branch history after a
  manual semantic merge.

## Why the implementation was not copied wholesale

| Area | Upstream behavior | Integrated behavior |
|---|---|---|
| Modern raw rows | Calls all Incidents-Complaints rows `rides`, materializes about 23.8M filler rows, and uses them as a denominator | Stream-filters structural all-N/redacted rows; never treats them as rides or negative samples |
| Trend conclusion | Makes an eight-block mixed-schema negative-binomial fit the headline result | Uses six comparable 2025+ windows as primary; mixed 2024/2025 history is sensitivity only |
| Collision frequency | Uses row-level actor flags or legacy aggregate totals | Uses location totals for frequency and actor rows for severity, preserving the reconciliation gap |
| Consequence | Does not load severity but states there are no severe/fatal PUDO collisions | Loads severity, collapses multi-label flags, reports one severe and zero fatality-coded rows |
| Missing data | Warns and can still write partial outputs followed by `[done]` | Fails on missing periods/months, null critical values, non-positive exposure, or null required rates |
| Redaction | Converts null flags to `False` in several paths | Preserves redacted/blank as unknown |
| Verification | No regression tests added | Regression tests cover schema, TCPID, filler rows, redaction, location reconciliation, severity, coverage, and CLI-critical rates |

The integration also rejects conflicting revisions for the same
`period × carrier × tract` key instead of summing both versions. Exact duplicate
location rows are deduplicated safely.

## Reconciliation facts checked

- December 2024 PUDO collisions: aggregate `CollisionsPUDOAll = 0`, while the
  location table and hourly bins support 8. The integrated summary uses 8 and
  exposes the disagreement.
- 2025 Q1: incident actor rows identify 33; location aggregate reports 34.
- 2026 Q2: incident actor rows identify 63; location aggregate reports 65.
- Across 2025+, location totals give 318 PUDO collisions; 315 actor-linked rows
  support consequence cross-tabs. Of those rows, 23 have a positive listed
  severity, 12 are minor-or-worse, one is severe, and none is fatality-coded.

## Statistical interpretation

The significant decline reported by the mixed-schema upstream model is not a
safe headline because the 2024/2025 reporting redesign is inseparable from the
time term. In the comparable modern era, the complaint-rate estimate is near
flat and statistically uncertain. The collision-rate point estimate declines,
but its conservative interval still includes no change. Both raw counts and
exposure-adjusted rates should be shown.

This review is about final observable behavior, not authorship. The upstream
ideas were compared function by function; overlapping code was retained only
where it preserved the stronger validation and the correct statistical grain.
