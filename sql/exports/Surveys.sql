-- Survey responses keyed to the call they rate, so they filter by call date, queue and agent
SELECT
    s.response_id, s.interaction_id, c.date_key, c.queue_id, c.employee_id,
    s.response_ts_local, s.csat, s.nps,
    CASE WHEN s.nps >= 9 THEN 'Promoter' WHEN s.nps >= 7 THEN 'Passive' WHEN s.nps IS NOT NULL THEN 'Detractor' END AS nps_group,
    s.fcr_self_reported, s.verbatim
FROM fact_survey AS s
JOIN fact_call   AS c ON c.interaction_id = s.interaction_id
ORDER BY s.response_ts_local
