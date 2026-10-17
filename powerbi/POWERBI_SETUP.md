# Power BI setup

The pipeline writes one workbook, `contact_centre_model.xlsx`, with every model table as a named Excel table.
Power BI reads that workbook. Because the pipeline overwrites the same file under the same name every month,
**the semantic model is built once and then refreshes itself**.

```
python pipeline ──▶ OneDrive/EDA_Contact_Centre/powerbi/contact_centre_model.xlsx ──▶ Power BI semantic model ──▶ report
                     (overwritten each refresh)                                       (OneDrive sync, ~hourly,
                                                                                       or "Refresh now")
```

Why a workbook in OneDrive rather than a live MySQL connection: the Power BI service can only reach a database
on a laptop through an on-premises data gateway, and the gateway runs on Windows only. A file in OneDrive for
work or school is reached cloud-to-cloud, so no gateway is needed. In production at EDA, the same model would point
at the warehouse (or a gateway) instead. Only the source step changes; the measures and report stay the same.

---

## Using the included report (`contact_centre.pbix`)

[`contact_centre.pbix`](contact_centre.pbix) is the finished four-page report (Overview, Queues & Staffing, Agents,
Customers & Sales) with **September** loaded, as it stood before the October files arrived. Open it in **Power BI
Desktop** and every page works straight away (month-on-month shows "--": there is no August). Connect it to your
own pipeline as below, run the October refresh, click Refresh, and watch it roll forward to October.

It was built in Power BI web against the workbook in OneDrive, so its 8 queries still point at that OneDrive
address. To connect it to **your own** pipeline runs instead:

1. **Home → Transform data**. In the Power Query Editor, select `Agent`, then its **Source** step under
   *Applied steps*.
2. Replace the formula in the formula bar with (use your clone's path):
   ```
   = Excel.Workbook(File.Contents("C:\eda-contact-centre-pipeline\output\powerbi\contact_centre_model.xlsx"), null, true)
   ```
3. Do the same for `Calls`, `Date`, `Forecast`, `Interactions`, `Queue`, `RefreshLog` and `Surveys` (paste the same
   formula; only the Source step changes).
4. **Close & Apply**. If asked about privacy levels, choose *Organizational*.

From then on the monthly loop is: `make refresh` (or **Run monthly refresh** in `python app.py`), then **Home →
Refresh** in Power BI. Run `make setup` first and the report shows September only; refresh after October loads and
the Month slicer's *Latest month* moves to October by itself.

---

## Option A: Power BI web (works on a Mac)

### 1. Point the pipeline at OneDrive
In `.env`, set the export folder to a folder inside your synced OneDrive (work/school account, the same one you
sign in to Power BI with):

```
EXPORT_DIR=~/Library/CloudStorage/OneDrive-<YourOrg>/EDA_Contact_Centre/powerbi
REPORT_DIR=~/Library/CloudStorage/OneDrive-<YourOrg>/EDA_Contact_Centre/reports
```

Run `make setup` (loads September). Wait until OneDrive shows the file as synced.

### 2. Create the semantic model
1. Go to app.powerbi.com, open a workspace (My workspace is fine).
2. **New item → Semantic model → Excel** → **OneDrive** → pick `contact_centre_model.xlsx`.
3. Tick all tables: `Calls`, `Interactions`, `Surveys`, `Forecast`, `Date`, `Agent`, `Queue`, `RefreshLog`
   (optional: `AgentScorecard`, `Heatmap`, which are pre-computed SQL views kept for reconciliation).
4. Choose **Create a semantic model only**. Name it `EDA Contact Centre`.

If Excel isn't offered in that list, open any semantic model's **Get data**, choose **Excel workbook**, and paste
the file's OneDrive link (Organisational account sign-in). It's still a cloud source, so no gateway is needed.

### 3. Model it (semantic model → **Open semantic model** → switch to **Editing**)

**Data types:** set `Date[Date]`, `Calls[call_date]`, `Interactions[call_date]`, `Forecast[forecast_date]` to *Date*.

**Mark as date table:** right-click `Date` → *Mark as date table* → column `Date`.

**Sort by column:** `Date[Day Name]` by `Date[Day of Week]`, `Date[Month]` by `Date[Month Number]`.

**Reporting Month as text:** in Power Query set `Date[Reporting Month]` (and `RefreshLog[Reporting Month]`) to
*Text*, otherwise "2026-09" is auto-detected as a date.

**Month Selector** (calculated column on `Date`, used by the Month slicer). "Latest month" always points at the newest
loaded month, so after each refresh the report rolls forward without anyone touching the slicer:

```
Month Selector =
VAR LatestStart = MAX ( 'Date'[Month Start] )
RETURN IF ( 'Date'[Month Start] = LatestStart, "Latest month", FORMAT ( 'Date'[Month Start], "mm-yyyy" ) )
```

Sort it by `Date[Month Start]` so months stay in date order across years.

**Relationships** (all many-to-one, single direction, from fact to dimension):

| From (many)              | To (one)            |
|--------------------------|---------------------|
| `Calls[date_key]`        | `Date[date_key]`    |
| `Calls[queue_id]`        | `Queue[queue_id]`   |
| `Calls[employee_id]`     | `Agent[employee_id]`|
| `Interactions[date_key]` | `Date[date_key]`    |
| `Interactions[queue_id]` | `Queue[queue_id]`   |
| `Interactions[employee_id]` | `Agent[employee_id]` |
| `Surveys[date_key]`      | `Date[date_key]`    |
| `Surveys[queue_id]`      | `Queue[queue_id]`   |
| `Surveys[employee_id]`   | `Agent[employee_id]`|
| `Forecast[date_key]`     | `Date[date_key]`    |
| `Forecast[queue_id]`     | `Queue[queue_id]`   |

Hide the key columns (`date_key`, `queue_id`, `employee_id`, `interaction_id`) in report view.

**Measures, fastest way:** open **DAX query view → New query**, paste [`measures_bulk.dax`](measures_bulk.dax) (every measure in one `DEFINE` block, rebuilt by `python scripts/build_bulk_measures.py`), click **Update model**, then set the format strings shown in `measures.dax`.

**Theme:** *View → Themes → Browse for themes* → [`eda_theme.json`](eda_theme.json) (neutral base; the brand colours switch via the `Brand … Colour` measures used as *fx* field values).

**Or one at a time:** add each measure from [`measures.dax`](measures.dax) with *New measure*, on the home table noted in
the comments, and set the format string shown. Optional tidy-up: *New table* → `_Measures = { BLANK() }`, hide its
column, and keep all measures there.

### 4. Turn on refresh
Semantic model **Settings** → keep **OneDrive refresh** on (Power BI checks the file about hourly).
For a fixed monthly cadence you can also add a **scheduled refresh** (credentials: OAuth2, organisational account).
After running October, **Refresh now** if you don't want to wait.

### 5. Build the report
Suggested four pages. Every number comes from a measure, so all pages respond to the Month and Brand slicers.

**1. Overview**
- Slicers: `Date[Month Selector]` (select *Latest month*), `Queue[Brand]`
- Cards: Calls Offered (+ Calls Offered MoM %), Service Level % (+ SL vs Target), Abandon Rate %, ASA, AHT (mm:ss),
  Avg CSAT, NPS Score, FCR %, Conversion %
- Line and column chart: `Date[Date]` × Calls Offered (columns), Forecast Offered (line), Service Level % (secondary axis)
- Text boxes: `Report Title`, `Data As At`, `Worst SL Day`, `Top Repeat Reason`

**2. Queues and staffing**
- Matrix: rows `Queue[Brand]` → `Queue[Queue]`; values Offered, Forecast Offered, Forecast Variance %, Service Level %,
  Blended SL Target %, Abandon Rate %, ASA, AHT. Conditional formatting on Service Level % → *Field value* → `SL Status Colour`
- Heatmap matrix: rows `Date[Day Name]`, columns `Calls[hour_of_day]`, value Service Level %, background colour scale
- Clustered columns: `Date[Date]` × Required Hours vs Scheduled Hours

**3. Agents**
- Table: `Agent[Team]`, `Agent[Agent]`, Calls Answered, AHT, Agent AHT vs Team, Hold %, Transfer Rate %, Avg CSAT,
  Agent CSAT vs Team, FCR %, Conversion %, Agent AHT Rank
- Scatter: AHT (x) vs Avg CSAT (y), details `Agent[Agent]`, legend `Agent[Team]`

**4. Customers and sales**
- Bar: `Interactions[contact_reason]` × Repeat Contacts, tooltip FCR %
- Columns: `Interactions[product]` × Policies Sold and Premium Written
- NPS Score and CSAT by `Queue[Brand]` and `Queue[Queue]`
- Table: `Surveys[verbatim]`, `Surveys[csat]` filtered to CSAT ≤ 2 (what unhappy customers say)

### 6. Share it
- **File → Download this file** (.pbix) and commit it to `powerbi/` in the repo, plus screenshots to `docs/`.
- If your tenant allows external sharing, share the report link. Otherwise the repo, screenshots and .pbix are the
  hand-off.

---

## Option B: Power BI Desktop (Windows)

Either:
- **Get data → Excel workbook** → `output/powerbi/contact_centre_model.xlsx`, then follow steps 3 and 5 above; or
- **Get data → MySQL database** → server `localhost:3307`, database `contact_centre`. Import the tables
  directly (the queries in `sql/exports/` show exactly what each model table contains).

To use the finished report instead of building one, see [Using the included report](#using-the-included-report-contact_centrepbix) above.
