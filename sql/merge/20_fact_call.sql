-- Month-partition swap: remove the month, reload it. Re-running a month is idempotent.
DELETE FROM fact_call WHERE reporting_month = :month;

INSERT INTO fact_call (
    interaction_id, reporting_month, date_key, call_date, start_ts_local, hour_of_day, queue_id, employee_id,
    is_answered, is_abandoned, is_short_abandon, wait_sec, talk_sec, hold_sec, acw_sec, handle_sec,
    is_transferred, answered_in_sl
)
SELECT
    s.interaction_id,
    s.reporting_month,
    CAST(DATE_FORMAT(s.call_date, '%Y%m%d') AS UNSIGNED),
    s.call_date,
    s.start_ts_local,
    s.hour_of_day,
    s.queue_id,
    s.employee_id,
    s.is_answered,
    s.is_abandoned,
    s.is_short_abandon,
    s.wait_sec,
    s.talk_sec,
    s.hold_sec,
    s.acw_sec,
    s.talk_sec + s.hold_sec + s.acw_sec,
    s.is_transferred,
    CASE WHEN s.is_answered = 1 AND s.wait_sec <= q.sl_target_sec THEN 1 ELSE 0 END
FROM stg_calls AS s
JOIN dim_queue AS q ON q.queue_id = s.queue_id
WHERE s.reporting_month = :month;
