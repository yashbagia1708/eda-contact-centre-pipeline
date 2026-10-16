-- =====================================================================
-- Reference data: Queensland public holidays and the date dimension.
-- dim_date is generated with a recursive CTE, so there is no calendar
-- file to maintain. Re-running is safe (INSERT IGNORE / upsert).
-- =====================================================================

INSERT IGNORE INTO ref_public_holiday (holiday_date, holiday_name) VALUES
    ('2026-01-01', 'New Year''s Day'),
    ('2026-01-26', 'Australia Day'),
    ('2026-04-03', 'Good Friday'),
    ('2026-04-04', 'Easter Saturday'),
    ('2026-04-06', 'Easter Monday'),
    ('2026-04-25', 'Anzac Day'),
    ('2026-05-04', 'Labour Day'),
    ('2026-10-05', 'King''s Birthday'),
    ('2026-12-25', 'Christmas Day'),
    ('2026-12-26', 'Boxing Day'),
    ('2026-12-28', 'Boxing Day (additional day)');

INSERT INTO dim_date (
    date_key, full_date, year_num, month_num, month_name, month_start, reporting_month,
    week_start, day_of_month, day_of_week, day_name, is_weekend, is_public_holiday, holiday_name
)
SELECT * FROM (
    WITH RECURSIVE calendar AS (
        SELECT DATE('2026-01-01') AS dt
        UNION ALL
        SELECT dt + INTERVAL 1 DAY FROM calendar WHERE dt < '2027-12-31'
    )
    SELECT
        CAST(DATE_FORMAT(c.dt, '%Y%m%d') AS UNSIGNED) AS date_key,
        c.dt                                          AS full_date,
        YEAR(c.dt)                                    AS year_num,
        MONTH(c.dt)                                   AS month_num,
        DATE_FORMAT(c.dt, '%b')                       AS month_name,
        DATE_FORMAT(c.dt, '%Y-%m-01')                 AS month_start,
        DATE_FORMAT(c.dt, '%Y-%m')                    AS reporting_month,
        c.dt - INTERVAL WEEKDAY(c.dt) DAY             AS week_start,
        DAY(c.dt)                                     AS day_of_month,
        WEEKDAY(c.dt) + 1                             AS day_of_week,
        DAYNAME(c.dt)                                 AS day_name,
        WEEKDAY(c.dt) >= 5                            AS is_weekend,
        h.holiday_date IS NOT NULL                    AS is_public_holiday,
        h.holiday_name                                AS holiday_name
    FROM calendar AS c
    LEFT JOIN ref_public_holiday AS h ON h.holiday_date = c.dt
) AS src
ON DUPLICATE KEY UPDATE
    is_public_holiday = src.is_public_holiday,
    holiday_name      = src.holiday_name;
