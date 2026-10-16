SELECT queue_id, brand AS `Brand`, queue_function AS `Queue`, sl_target_sec AS `SL Target (sec)`, sl_target_pct AS `SL Target %`
FROM dim_queue
ORDER BY brand, queue_function
