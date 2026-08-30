# pudo-pipeline

Reproducible pipeline for analyzing **PUDO (pick-up/drop-off) complaint risk**
in Waymo's CPUC AV Deployment quarterly reports, covering **2024 Q3 – 2026 Q2**.

Downloads the public report zips from the CPUC website, extracts the
Incidents-Complaints, Incidents-Location, and Month-Level files; validates
carrier identity, redaction, schema, and period coverage; and compiles them
into four parquet datasets ready for analysis.

## Quick start

```bash
# pip
pip install -e .

# or conda
conda create -n pudo python=3.11 -y && conda activate pudo && pip install -e .

# run the pipeline (downloads 9 report zips from cpuc.ca.gov)
pudo-build

# while the same environment is still active, open the analysis notebook
jupyter lab notebooks/pudo_analysis.ipynb

# run regression tests
python -m unittest discover -s tests -v
```

Already have the zips? Drop them in `data/raw/` named `<period_id>.zip`
(see `src/pudo_pipeline/config.py` for period ids), or put extracted folders
under `data/extracted/<period_id>/`, then run `pudo-build --no-download`.

Set `PUDO_DATA_DIR=/some/path` to relocate the data directory.

## Outputs (`data/parquet/`)

| File | Grain | Contents |
|---|---|---|
| `complaints.parquet` | source-dependent | 2024 aggregate count rows and analytically relevant 2025+ event rows; flags are nullable and highest PUDO collision severity is mutually exclusive |
| `monthly_activity.parquet` | one row per month | trips, VMT by period (P1 deadhead / P2 en-route / P3 passenger), `vmt_total`, PMT, passengers |
| `collision_locations.parquet` | one row per tract/reporting period | direct `CollisionsAll` and `CollisionsPUDO` aggregates used to reconcile row-level actor flags |
| `pudo_summary.parquet` | one row per reporting period | complaints, primary/reconciled collision counts, severity counts, VMT/trips, rates, actual midpoint, and elapsed months |

The build exits with an error instead of writing outputs if a reporting period
or expected month is missing, if critical numeric fields cannot be parsed, or
if a required rate would be null.

## Data notes & caveats

- **TCPID is the carrier permit ID** (identifies Waymo), not a record key —
  there is no row-level join across files. Complaints join to exposure at the
  reporting-period level.
- **Incident timestamps and locations are redacted** in the public files, so
  complaints carry period-level dates only (`month` is null). Monthly VMT has
  real Year/Month columns.
- **Reporting periods changed 2025-01-01** from Sep–Nov style quarters to
  calendar quarters. The 2024 portion of the window is covered by the
  Jun–Aug 2024, Sep–Nov 2024, and Dec 2024 (one-month stub) reports. The
  Poisson trend model in the notebook handles unequal exposure via the
  VMT offset and actual window midpoints. For Missy's requested 8-block Y1/Y2
  comparison, Sep–Nov and Dec 2024 are combined into one clearly labeled
  transition block because redacted complaint dates cannot be reassigned to
  calendar quarters.
- CPUC changed complaint schemas in 2025. The pipeline maps legacy aggregate
  fields such as `ComplaintsPUDO` to the canonical count columns used for the
  2025+ row-level Y/N files.
- Modern archives contain millions of repeated all-N/redacted template rows.
  The loader projection- and stream-filters them instead of writing them as
  pretend incidents or negative samples. The output is an analytic event view;
  the source ZIP remains the audit record.
- `Y`/`N` flags become 1/0, while `Redacted`, blank, and NULL remain null.
  In particular, the public travel-lane field is not interpreted as zero when
  it is redacted.
- Collision frequency uses the tract-level
  `Incidents-Location.CollisionsPUDO` aggregate whenever it is available;
  modern periods require it. Incident rows are used for actor and severity
  cross-tabs. The summary retains both counts, the chosen source, and their
  reconciliation gap—including the 2024 source discrepancies.
- Severity flags are multi-label. The pipeline also emits one mutually
  exclusive highest-listed-severity indicator per PUDO collision row; a row
  without a positive severity flag is labeled `No listed severity flag`, not
  `no harm`.
- CPUC renamed the fleet-level monthly file from `Month_Level` to
  `Month_Part0` in 2026. Both names are accepted, while `Monthly_Tract` files
  are deliberately excluded.
- The Jun–Aug 2024 zip also contains Cruise files. The loader excludes Drivered
  folders and filters the carrier identifiers to Waymo before aggregation.
- Legacy and modern travel-lane PUDO totals may be redacted. These remain null
  (unknown), rather than being converted to zero.
- CPUC uses comma-formatted numeric strings. The parser removes thousands
  separators before conversion and fails fast if critical values remain null.
- Source page: CPUC AV Program Quarterly Reporting
  (cpuc.ca.gov → Licensing → Autonomous Vehicle Programs → Quarterly Reporting).
