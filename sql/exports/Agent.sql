SELECT employee_id, agent_name AS `Agent`, team AS `Team`, team_leader AS `Team Leader`, site AS `Site`,
       start_date AS `Start Date`, end_date AS `End Date`, fte AS `FTE`, status AS `Status`
FROM dim_agent
ORDER BY team, agent_name
