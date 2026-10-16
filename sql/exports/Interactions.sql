-- CRM cases with the behavioural FCR flags computed in vw_interaction_fcr
SELECT
    i.case_id, i.interaction_id, CAST(DATE_FORMAT(i.call_date, '%Y%m%d') AS UNSIGNED) AS date_key, i.call_date,
    c.queue_id, COALESCE(i.employee_id, 'UNKNOWN') AS employee_id, i.brand, i.policy_number, i.contact_reason,
    i.outcome, i.is_sale, i.product, i.annual_premium, i.fcr_eligible, i.fcr_window_complete,
    i.repeat_within_7d, i.next_contact_reason
FROM vw_interaction_fcr AS i
LEFT JOIN fact_call AS c ON c.interaction_id = i.interaction_id
ORDER BY i.created_ts_local
