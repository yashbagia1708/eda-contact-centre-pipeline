SELECT agent_name, team, team_leader, tenure_band, calls_handled, calls_per_day, aht_sec, team_avg_aht_sec, hold_pct,
       transfer_rate, avg_csat, team_avg_csat, csat_quartile, sales, conversion_rate, fcr_rate, aht_rank_in_team, csat_rank_in_team
FROM vw_agent_monthly_scorecard WHERE reporting_month = :month ORDER BY team, aht_rank_in_team
