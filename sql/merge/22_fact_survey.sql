-- Customers sometimes submit the survey twice: the latest response per call wins (window function).
-- The rule holds across months too, so which month keeps a repeated survey doesn't depend on load order:
-- loading Sep then Oct, or Oct then Sep, ends with the same rows.
DELETE FROM fact_survey WHERE reporting_month = :month;

-- Another month holds an older response for a call this month's file answers again: the newer one replaces it
DELETE f FROM fact_survey AS f
JOIN (
    SELECT interaction_id, response_ts_local, response_id
    FROM (
        SELECT s.interaction_id, s.response_ts_local, s.response_id,
               ROW_NUMBER() OVER (PARTITION BY s.interaction_id
                                  ORDER BY s.response_ts_local DESC, s.response_id DESC) AS rn
        FROM stg_survey AS s
        WHERE s.reporting_month = :month
    ) AS r
    WHERE r.rn = 1
) AS newest ON newest.interaction_id = f.interaction_id
WHERE f.reporting_month <> :month
  AND (f.response_ts_local, f.response_id) < (newest.response_ts_local, newest.response_id);

INSERT INTO fact_survey (
    response_id, interaction_id, reporting_month, response_ts_local, csat, nps, fcr_self_reported, verbatim
)
WITH ranked AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (PARTITION BY s.interaction_id ORDER BY s.response_ts_local DESC, s.response_id DESC) AS rn
    FROM stg_survey AS s
    WHERE s.reporting_month = :month
)
SELECT response_id, interaction_id, reporting_month, response_ts_local, csat, nps, fcr_self_reported, verbatim
FROM ranked
WHERE rn = 1
  AND NOT EXISTS (                       -- another month already holds a newer (or the same) response
      SELECT 1 FROM fact_survey AS f
      WHERE f.interaction_id = ranked.interaction_id
        AND f.reporting_month <> :month
        AND (f.response_ts_local, f.response_id) >= (ranked.response_ts_local, ranked.response_id)
  );
