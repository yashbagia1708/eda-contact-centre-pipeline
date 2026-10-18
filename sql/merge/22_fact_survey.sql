-- Customers sometimes answer the survey twice: keep the latest response per call.
-- Same rule across months, so it doesn't matter which month gets loaded first.
DELETE FROM fact_survey WHERE reporting_month = :month;

-- Another month already has an older response for the same call? Replace it with this month's newer one
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
  AND NOT EXISTS (                       -- skip if another month already has a newer (or the same) one
      SELECT 1 FROM fact_survey AS f
      WHERE f.interaction_id = ranked.interaction_id
        AND f.reporting_month <> :month
        AND (f.response_ts_local, f.response_id) >= (ranked.response_ts_local, ranked.response_id)
  );
