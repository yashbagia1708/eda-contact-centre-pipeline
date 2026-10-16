-- Average demand and service level by weekday and hour: the staffing view
CREATE OR REPLACE VIEW vw_interval_heatmap AS
WITH by_day_hour AS (
    SELECT
        c.reporting_month,
        d.day_of_week,
        d.day_name,
        c.hour_of_day,
        c.call_date,
        COUNT(*)              AS offered,
        SUM(c.answered_in_sl) AS answered_in_sl,
        SUM(c.is_short_abandon) AS short_abandoned
    FROM fact_call AS c
    JOIN dim_date  AS d ON d.full_date = c.call_date
    WHERE d.is_public_holiday = 0
    GROUP BY c.reporting_month, d.day_of_week, d.day_name, c.hour_of_day, c.call_date
)
SELECT
    reporting_month,
    day_of_week,
    day_name,
    hour_of_day,
    COUNT(DISTINCT call_date)                       AS days_observed,
    ROUND(AVG(offered), 1)                          AS avg_offered,
    ROUND(SUM(answered_in_sl) / NULLIF(SUM(offered) - SUM(short_abandoned), 0), 4) AS service_level_pct
FROM by_day_hour
GROUP BY reporting_month, day_of_week, day_name, hour_of_day;
