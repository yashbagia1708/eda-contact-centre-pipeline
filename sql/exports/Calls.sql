SELECT
    interaction_id, date_key, call_date, start_ts_local, hour_of_day, queue_id,
    employee_id,
    is_answered, is_abandoned, is_short_abandon, wait_sec, talk_sec, hold_sec, acw_sec, handle_sec,
    is_transferred, answered_in_sl
FROM fact_call
ORDER BY start_ts_local
