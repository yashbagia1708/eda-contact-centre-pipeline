-- Month x brand headline KPIs, with an all-brand total (ROLLUP) and month-on-month change (LAG)
CREATE OR REPLACE VIEW vw_monthly_kpi_summary AS
WITH calls AS (
    SELECT
        c.reporting_month,
        COALESCE(q.brand, 'All brands') AS brand_label,
        GROUPING(q.brand)               AS is_total,
        COUNT(*)                        AS offered,
        SUM(c.is_answered)              AS answered,
        SUM(c.is_abandoned) - SUM(c.is_short_abandon) AS abandoned,
        SUM(c.is_short_abandon)         AS short_abandoned,
        SUM(c.answered_in_sl)           AS answered_in_sl,
        SUM(CASE WHEN c.is_answered = 1 THEN c.wait_sec END) AS answer_wait_sec,
        SUM(c.handle_sec)               AS handle_sec
    FROM fact_call AS c
    JOIN dim_queue AS q ON q.queue_id = c.queue_id
    GROUP BY c.reporting_month, q.brand WITH ROLLUP
    HAVING c.reporting_month IS NOT NULL
),
cx AS (
    SELECT
        c.reporting_month,
        COALESCE(q.brand, 'All brands') AS brand_label,
        AVG(s.csat)                     AS avg_csat,
        (SUM(s.nps >= 9) - SUM(s.nps <= 6)) / NULLIF(COUNT(s.nps), 0) AS nps
    FROM fact_survey AS s
    JOIN fact_call   AS c ON c.interaction_id = s.interaction_id
    JOIN dim_queue   AS q ON q.queue_id = c.queue_id
    GROUP BY c.reporting_month, q.brand WITH ROLLUP
    HAVING c.reporting_month IS NOT NULL
),
outcomes AS (
    SELECT
        i.reporting_month,
        COALESCE(i.brand, 'All brands') AS brand_label,
        SUM(CASE WHEN i.contact_reason IN ('New Quote', 'Quote Follow-up', 'Add Vehicle') THEN 1 ELSE 0 END) AS sales_opportunities,
        SUM(i.is_sale)                  AS sales,
        SUM(i.annual_premium)           AS premium_written,
        SUM(CASE WHEN i.fcr_eligible = 1 AND i.fcr_window_complete = 1 THEN 1 ELSE 0 END)                           AS fcr_contacts,
        SUM(CASE WHEN i.fcr_eligible = 1 AND i.fcr_window_complete = 1 AND i.repeat_within_7d = 0 THEN 1 ELSE 0 END) AS fcr_resolved
    FROM vw_interaction_fcr AS i
    GROUP BY i.reporting_month, i.brand WITH ROLLUP
    HAVING i.reporting_month IS NOT NULL
),
kpis AS (
    SELECT
        c.reporting_month,
        c.brand_label,
        c.is_total,
        c.offered,
        c.answered,
        ROUND(c.answered_in_sl / NULLIF(c.offered - c.short_abandoned, 0), 4) AS service_level_pct,
        ROUND(c.abandoned / NULLIF(c.offered - c.short_abandoned, 0), 4)      AS abandon_rate,
        ROUND(c.answer_wait_sec / NULLIF(c.answered, 0), 1)                   AS asa_sec,
        ROUND(c.handle_sec / NULLIF(c.answered, 0), 0)                        AS aht_sec,
        ROUND(x.avg_csat, 2)                                                  AS avg_csat,
        ROUND(x.nps * 100, 1)                                                 AS nps,
        ROUND(o.fcr_resolved / NULLIF(o.fcr_contacts, 0), 4)                  AS fcr_rate,
        o.sales,
        ROUND(o.sales / NULLIF(o.sales_opportunities, 0), 4)                  AS conversion_rate,
        o.premium_written
    FROM calls AS c
    LEFT JOIN cx       AS x ON x.reporting_month = c.reporting_month AND x.brand_label = c.brand_label
    LEFT JOIN outcomes AS o ON o.reporting_month = c.reporting_month AND o.brand_label = c.brand_label
)
SELECT
    k.*,
    k.offered           - LAG(k.offered)           OVER w AS offered_mom,
    k.service_level_pct - LAG(k.service_level_pct) OVER w AS service_level_mom_pts,
    k.abandon_rate      - LAG(k.abandon_rate)      OVER w AS abandon_rate_mom_pts,
    k.aht_sec           - LAG(k.aht_sec)           OVER w AS aht_mom_sec,
    k.avg_csat          - LAG(k.avg_csat)          OVER w AS csat_mom,
    k.conversion_rate   - LAG(k.conversion_rate)   OVER w AS conversion_mom_pts
FROM kpis AS k
WINDOW w AS (PARTITION BY k.brand_label ORDER BY k.reporting_month);
