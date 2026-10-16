SELECT * FROM vw_monthly_kpi_summary WHERE reporting_month <= :month ORDER BY is_total DESC, brand_label, reporting_month
