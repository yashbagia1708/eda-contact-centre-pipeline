-- Why customers call, and which reasons drive repeat contact
CREATE OR REPLACE VIEW vw_contact_reason_summary AS
WITH reasons AS (
    SELECT
        reporting_month,
        brand,
        contact_reason,
        COUNT(*) AS contacts,
        SUM(CASE WHEN fcr_eligible = 1 AND fcr_window_complete = 1 THEN 1 ELSE 0 END) AS fcr_contacts,
        SUM(CASE WHEN fcr_eligible = 1 AND fcr_window_complete = 1 AND repeat_within_7d = 1 THEN 1 ELSE 0 END) AS repeat_contacts
    FROM vw_interaction_fcr
    GROUP BY reporting_month, brand, contact_reason
)
SELECT
    r.*,
    ROUND(1 - r.repeat_contacts / NULLIF(r.fcr_contacts, 0), 4) AS fcr_rate,
    ROUND(r.contacts / SUM(r.contacts) OVER (PARTITION BY r.reporting_month, r.brand), 4) AS share_of_contacts,
    RANK() OVER (PARTITION BY r.reporting_month, r.brand ORDER BY r.contacts DESC) AS volume_rank
FROM reasons AS r;
