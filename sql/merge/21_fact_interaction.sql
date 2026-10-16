DELETE FROM fact_interaction WHERE reporting_month = :month;

INSERT INTO fact_interaction (
    case_id, interaction_id, reporting_month, created_ts_local, call_date, employee_id, brand,
    policy_number, contact_reason, outcome, is_sale, product, annual_premium
)
SELECT
    case_id, interaction_id, reporting_month, created_ts_local, DATE(created_ts_local), employee_id, brand,
    policy_number, contact_reason, outcome, is_sale, product, annual_premium
FROM stg_crm
WHERE reporting_month = :month;
