SELECT CAST(DATE_FORMAT(forecast_date, '%Y%m%d') AS UNSIGNED) AS date_key, forecast_date, queue_id,
       forecast_offered, forecast_aht_sec, scheduled_hours
FROM fact_forecast
ORDER BY forecast_date, queue_id
