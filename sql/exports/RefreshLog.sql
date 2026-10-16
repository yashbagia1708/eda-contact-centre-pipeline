-- One row per loaded month: lets the dashboard show 'data as at' and when it last refreshed
SELECT reporting_month AS `Reporting Month`, MAX(finished_at) AS `Last Refreshed`, MAX(rows_loaded) AS `Rows Loaded`
FROM etl_run_log
WHERE status = 'SUCCESS'
GROUP BY reporting_month
ORDER BY reporting_month
