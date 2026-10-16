SELECT call_date, day_name, brand, queue_function, offered, answered, abandoned, service_level_pct, sl_target_pct,
       abandon_rate, asa_sec, aht_sec, forecast_offered, forecast_variance_pct
FROM vw_daily_queue_performance WHERE reporting_month = :month ORDER BY call_date, brand, queue_function
