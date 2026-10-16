-- Customers sometimes submit the survey twice: keep the latest response per call (window function)
DELETE FROM fact_survey WHERE reporting_month = :month;

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
  AND NOT EXISTS (                       -- already captured from an earlier month's file
      SELECT 1 FROM fact_survey AS f
      WHERE f.interaction_id = ranked.interaction_id AND f.reporting_month <> :month
  );
