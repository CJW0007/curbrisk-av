# pudo-pipeline

Reproducible pipeline for analyzing **PUDO (pick-up/drop-off) complaint risk**
in Waymo's CPUC AV Deployment quarterly reports, covering **2024 Q3 – 2026 Q2**.

Downloads the public report zips from the CPUC website, extracts the
Incidents-Complaints and Month-Level files, validates carrier identity and
period coverage, and compiles them into three parquet datasets ready for
analysis.

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
| `complaints.parquet` | source-dependent | 2024 aggregate count rows and 2025+ row-level flags normalized to canonical count-contribution columns; `record_grain` identifies the source schema |
| `monthly_activity.parquet` | one row per month | trips, VMT by period (P1 deadhead / P2 en-route / P3 passenger), `vmt_total`, PMT, passengers |
| `pudo_summary.parquet` | one row per reporting period | PUDO complaint/travel-lane/collision counts joined to VMT & trips, rates per 100k, actual period midpoint and elapsed months |

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
- CPUC renamed the fleet-level monthly file from `Month_Level` to
  `Month_Part0` in 2026. Both names are accepted, while `Monthly_Tract` files
  are deliberately excluded.
- The Jun–Aug 2024 zip also contains Cruise files. The loader excludes Drivered
  folders and filters the carrier identifiers to Waymo before aggregation.
- Legacy travel-lane PUDO totals may be redacted. These remain null (unknown),
  rather than being converted to zero.
- CPUC uses comma-formatted numeric strings. The parser removes thousands
  separators before conversion and fails fast if critical values remain null.
- Source page: CPUC AV Program Quarterly Reporting
  (cpuc.ca.gov → Licensing → Autonomous Vehicle Programs → Quarterly Reporting).
