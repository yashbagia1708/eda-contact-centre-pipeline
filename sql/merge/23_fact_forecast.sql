DELETE FROM fact_forecast WHERE reporting_month = :month;

INSERT INTO fact_forecast (forecast_date, queue_id, reporting_month, forecast_offered, forecast_aht_sec, scheduled_hours)
SELECT forecast_date, queue_id, reporting_month, forecast_offered, forecast_aht_sec, scheduled_hours
FROM stg_forecast
WHERE reporting_month = :month;
