-- Upsert queue dimension from the business-maintained mapping (config/queue_mapping.csv)
INSERT INTO dim_queue (queue_id, brand, queue_function, sl_target_sec, sl_target_pct)
SELECT DISTINCT queue_id, brand, queue_function, sl_target_sec, sl_target_pct
FROM stg_queue AS s
ON DUPLICATE KEY UPDATE
    brand          = s.brand,
    queue_function = s.queue_function,
    sl_target_sec  = s.sl_target_sec,
    sl_target_pct  = s.sl_target_pct;
