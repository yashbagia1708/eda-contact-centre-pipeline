-- Daily performance per queue against SL target and the WFM forecast
CREATE OR REPLACE VIEW vw_daily_queue_performance AS
WITH call_stats AS (
    SELECT
        call_date,
        queue_id,
        COUNT(*)                                             AS offered,
        SUM(is_answered)                                     AS answered,
        SUM(is_abandoned) - SUM(is_short_abandon)            AS abandoned,
        SUM(is_short_abandon)                                AS short_abandoned,
        SUM(answered_in_sl)                                  AS answered_in_sl,
        SUM(CASE WHEN is_answered = 1 THEN wait_sec END)     AS answer_wait_sec,
        SUM(handle_sec)                                      AS handle_sec,
        SUM(is_transferred)                                  AS transferred
    FROM fact_call
    GROUP BY call_date, queue_id
)
SELECT
    c.call_date,
    d.reporting_month,
    d.day_name,
    d.is_public_holiday,
    q.queue_id,
    q.brand,
    q.queue_function,
    c.offered,
    c.answered,
    c.abandoned,
    c.short_abandoned,
    ROUND(c.answered_in_sl / NULLIF(c.offered - c.short_abandoned, 0), 4) AS service_level_pct,
    q.sl_target_pct,
    q.sl_target_sec,
    ROUND(c.abandoned / NULLIF(c.offered - c.short_abandoned, 0), 4)      AS abandon_rate,
    ROUND(c.answer_wait_sec / NULLIF(c.answered, 0), 1)                   AS asa_sec,
    ROUND(c.handle_sec / NULLIF(c.answered, 0), 1)                        AS aht_sec,
    f.forecast_offered,
    ROUND((c.offered - f.forecast_offered) / NULLIF(f.forecast_offered, 0), 4) AS forecast_variance_pct,
    f.scheduled_hours,
    ROUND(c.handle_sec / 3600, 1)                                         AS workload_hours
FROM call_stats AS c
JOIN dim_queue AS q ON q.queue_id = c.queue_id
JOIN dim_date  AS d ON d.full_date = c.call_date
LEFT JOIN fact_forecast AS f ON f.forecast_date = c.call_date AND f.queue_id = c.queue_id;
