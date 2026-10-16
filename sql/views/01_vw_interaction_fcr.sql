-- First contact resolution, measured from behaviour rather than survey answers:
-- a contact is "resolved first time" if the same policy does not call again within 7 days.
-- LEAD() finds each policy's next contact. Contacts in the last 7 days of loaded data
-- cannot be judged yet, so they are flagged fcr_window_complete = 0 and excluded from FCR.
CREATE OR REPLACE VIEW vw_interaction_fcr AS
WITH latest AS (
    SELECT MAX(created_ts_local) AS max_ts FROM fact_interaction
),
sequenced AS (
    SELECT
        i.*,
        LEAD(i.created_ts_local) OVER (PARTITION BY i.policy_number ORDER BY i.created_ts_local) AS next_contact_ts,
        LEAD(i.contact_reason)   OVER (PARTITION BY i.policy_number ORDER BY i.created_ts_local) AS next_contact_reason
    FROM fact_interaction AS i
)
SELECT
    s.case_id,
    s.interaction_id,
    s.reporting_month,
    s.created_ts_local,
    s.call_date,
    s.employee_id,
    s.brand,
    s.policy_number,
    s.contact_reason,
    s.outcome,
    s.is_sale,
    s.product,
    s.annual_premium,
    CASE
        WHEN s.policy_number IS NULL OR s.contact_reason IN ('New Quote', 'Quote Follow-up', 'Add Vehicle') THEN 0
        ELSE 1
    END AS fcr_eligible,
    CASE WHEN s.created_ts_local + INTERVAL 7 DAY <= l.max_ts THEN 1 ELSE 0 END AS fcr_window_complete,
    CASE
        WHEN s.policy_number IS NULL THEN NULL
        WHEN s.next_contact_ts <= s.created_ts_local + INTERVAL 7 DAY THEN 1
        ELSE 0
    END AS repeat_within_7d,
    CASE WHEN s.policy_number IS NULL THEN NULL ELSE s.next_contact_reason END AS next_contact_reason
FROM sequenced AS s
CROSS JOIN latest AS l;
