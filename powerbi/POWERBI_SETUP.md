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

**Measures:** add each measure from [`measures.dax`](measures.dax) with *New measure*, on the home table noted in
the comments, and set the format string shown. Optional tidy-up: *New table* → `_Measures = { BLANK() }`, hide its
column, and keep all measures there.

### 4. Turn on refresh
Semantic model **Settings** → keep **OneDrive refresh** on (Power BI checks the file about hourly).
For a fixed monthly cadence you can also add a **scheduled refresh** (credentials: OAuth2, organisational account).
After running October, **Refresh now** if you don't want to wait.

### 5. Build the report
Suggested four pages. Every number comes from a measure, so all pages respond to the Month and Brand slicers.

**1. Overview**
- Slicers: `Date[Reporting Month]`, `Queue[Brand]`
- Cards: Calls Offered (+ Calls Offered MoM %), Service Level % (+ SL vs Target), Abandon Rate %, ASA, AHT (mm:ss),
  Avg CSAT, NPS, FCR %, Conversion %
- Line and column chart: `Date[Date]` × Calls Offered (columns), Forecast Offered (line), Service Level % (secondary axis)
- Text boxes: `Report Title`, `Data As At`, `Worst SL Day`, `Top Repeat Reason`

**2. Queues and staffing**
- Matrix: rows `Queue[Brand]` → `Queue[Queue]`; values Offered, Forecast Offered, Forecast Variance %, Service Level %,
  SL Target %, Abandon Rate %, ASA, AHT. Conditional formatting on Service Level % → *Field value* → `SL Status Colour`
- Heatmap matrix: rows `Date[Day Name]`, columns `Calls[hour_of_day]`, value Service Level %, background colour scale
- Clustered columns: `Date[Date]` × Required Hours vs Scheduled Hours

**3. Agents**
- Table: `Agent[Team]`, `Agent[Agent]`, Calls Answered, AHT, Agent AHT vs Team, Hold %, Transfer Rate %, Avg CSAT,
  Agent CSAT vs Team, FCR %, Conversion %, Agent AHT Rank
- Scatter: AHT (x) vs Avg CSAT (y), details `Agent[Agent]`, legend `Agent[Team]`

**4. Customers and sales**
- Bar: `Interactions[contact_reason]` × Repeat Contacts, tooltip FCR %
- Columns: `Interactions[product]` × Policies Sold and Premium Written
- NPS and CSAT by `Queue[Brand]` and `Queue[Queue]`
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

If you were given the `.pbix`: **Transform data → Data source settings → Change source** and point it at your own
`output/powerbi/contact_centre_model.xlsx`, then **Refresh**.
