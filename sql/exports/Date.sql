-- Date table for Power BI, trimmed to the months that have been loaded
SELECT
    d.date_key, d.full_date AS `Date`, d.year_num AS `Year`, d.month_num AS `Month Number`,
    d.month_name AS `Month`, d.month_start AS `Month Start`, d.reporting_month AS `Reporting Month`,
    d.week_start AS `Week Start`, d.day_of_week AS `Day of Week`, d.day_name AS `Day Name`,
    d.is_weekend AS `Is Weekend`, d.is_public_holiday AS `Is Public Holiday`, d.holiday_name AS `Holiday`
FROM dim_date AS d
WHERE d.full_date BETWEEN (SELECT MIN(month_start) FROM dim_date WHERE full_date = (SELECT MIN(call_date) FROM fact_call))
                      AND (SELECT LAST_DAY(MAX(call_date)) FROM fact_call)
ORDER BY d.full_date
