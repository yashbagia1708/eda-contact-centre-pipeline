-- Agent scorecard per month: productivity, quality, customer outcome, with
-- rankings and team comparisons via window functions.
CREATE OR REPLACE VIEW vw_agent_monthly_scorecard AS
WITH call_stats AS (
    SELECT
        reporting_month,
        employee_id,
        COUNT(*)                                          AS calls_handled,
        AVG(handle_sec)                                   AS aht_sec,
        SUM(hold_sec) / NULLIF(SUM(talk_sec + hold_sec), 0) AS hold_pct,
        AVG(is_transferred)                               AS transfer_rate,
        COUNT(DISTINCT call_date)                         AS days_worked
    FROM fact_call
    WHERE is_answered = 1 AND employee_id <> 'UNKNOWN'
    GROUP BY reporting_month, employee_id
),
survey_stats AS (
    SELECT
        c.reporting_month,
        c.employee_id,
        COUNT(s.csat)                                     AS survey_responses,
        AVG(s.csat)                                       AS avg_csat,
        AVG(CASE WHEN s.csat >= 4 THEN 1.0 WHEN s.csat IS NOT NULL THEN 0 END) AS csat_top2_pct
    FROM fact_survey AS s
    JOIN fact_call   AS c ON c.interaction_id = s.interaction_id
    GROUP BY c.reporting_month, c.employee_id
),
outcome_stats AS (
    SELECT
        reporting_month,
        employee_id,
        SUM(CASE WHEN contact_reason IN ('New Quote', 'Quote Follow-up', 'Add Vehicle') THEN 1 ELSE 0 END) AS sales_opportunities,
        SUM(is_sale)                                      AS sales,
        SUM(annual_premium)                               AS premium_written,
        SUM(CASE WHEN fcr_eligible = 1 AND fcr_window_complete = 1 THEN 1 ELSE 0 END)                         AS fcr_contacts,
        SUM(CASE WHEN fcr_eligible = 1 AND fcr_window_complete = 1 AND repeat_within_7d = 0 THEN 1 ELSE 0 END) AS fcr_resolved
    FROM vw_interaction_fcr
    GROUP BY reporting_month, employee_id
),
combined AS (
    SELECT
        cs.reporting_month,
        a.employee_id,
        a.agent_name,
        a.team,
        a.team_leader,
        CASE
            WHEN DATEDIFF(LAST_DAY(STR_TO_DATE(CONCAT(cs.reporting_month, '-01'), '%Y-%m-%d')), a.start_date) < 90
                THEN 'New starter (<90 days)'
            WHEN DATEDIFF(LAST_DAY(STR_TO_DATE(CONCAT(cs.reporting_month, '-01'), '%Y-%m-%d')), a.start_date) < 365
                THEN '3-12 months'
            ELSE '12 months +'
        END                                               AS tenure_band,
        cs.calls_handled,
        cs.days_worked,
        ROUND(cs.calls_handled / NULLIF(cs.days_worked, 0), 1) AS calls_per_day,
        ROUND(cs.aht_sec, 0)                              AS aht_sec,
        ROUND(cs.hold_pct, 4)                             AS hold_pct,
        ROUND(cs.transfer_rate, 4)                        AS transfer_rate,
        ss.survey_responses,
        ROUND(ss.avg_csat, 2)                             AS avg_csat,
        ROUND(ss.csat_top2_pct, 4)                        AS csat_top2_pct,
        os.sales_opportunities,
        os.sales,
        ROUND(os.sales / NULLIF(os.sales_opportunities, 0), 4) AS conversion_rate,
        os.premium_written,
        ROUND(os.fcr_resolved / NULLIF(os.fcr_contacts, 0), 4) AS fcr_rate
    FROM call_stats AS cs
    JOIN dim_agent         AS a  ON a.employee_id = cs.employee_id
    LEFT JOIN survey_stats AS ss ON ss.employee_id = cs.employee_id AND ss.reporting_month = cs.reporting_month
    LEFT JOIN outcome_stats AS os ON os.employee_id = cs.employee_id AND os.reporting_month = cs.reporting_month
)
SELECT
    c.*,
    ROUND(AVG(c.aht_sec)  OVER (PARTITION BY c.reporting_month, c.team), 0) AS team_avg_aht_sec,
    ROUND(AVG(c.avg_csat) OVER (PARTITION BY c.reporting_month, c.team), 2) AS team_avg_csat,
    RANK() OVER (PARTITION BY c.reporting_month, c.team ORDER BY c.aht_sec ASC)        AS aht_rank_in_team,
    RANK() OVER (PARTITION BY c.reporting_month, c.team ORDER BY c.avg_csat DESC)      AS csat_rank_in_team,
    NTILE(4) OVER (PARTITION BY c.reporting_month ORDER BY c.csat_top2_pct DESC)       AS csat_quartile,
    c.calls_handled - LAG(c.calls_handled) OVER (PARTITION BY c.employee_id ORDER BY c.reporting_month) AS calls_handled_mom_change
FROM combined AS c;
