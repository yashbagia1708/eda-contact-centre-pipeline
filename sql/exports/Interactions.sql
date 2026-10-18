-- CRM cases with the behavioural FCR flags computed in vw_interaction_fcr
-- Queue comes from the linked call. No call in telephony? Use the brand's 'Not linked to a call' queue,
-- so the case still counts towards its brand.
SELECT
    i.case_id, i.interaction_id, CAST(DATE_FORMAT(i.call_date, '%Y%m%d') AS UNSIGNED) AS date_key, i.call_date,
    COALESCE(c.queue_id, uq.queue_id) AS queue_id, COALESCE(i.employee_id, 'UNKNOWN') AS employee_id, i.brand, i.policy_number, i.contact_reason,
    i.outcome, i.is_sale, i.product, i.annual_premium, i.fcr_eligible, i.fcr_window_complete,
    i.repeat_within_7d, i.next_contact_reason
FROM vw_interaction_fcr AS i
LEFT JOIN fact_call AS c ON c.interaction_id = i.interaction_id
LEFT JOIN dim_queue AS uq ON uq.brand = i.brand AND uq.queue_function = 'Not linked to a call'
ORDER BY i.created_ts_local
