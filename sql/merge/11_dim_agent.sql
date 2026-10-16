-- Agent dimension: type-1 upsert from the WFM roster (latest roster wins)
INSERT INTO dim_agent (employee_id, login, agent_name, team, team_leader, site, start_date, end_date, fte, status)
SELECT employee_id, login, agent_name, team, team_leader, site, start_date, end_date, fte, status
FROM stg_roster AS s
ON DUPLICATE KEY UPDATE
    login       = s.login,
    agent_name  = s.agent_name,
    team        = s.team,
    team_leader = s.team_leader,
    site        = s.site,
    start_date  = s.start_date,
    end_date    = s.end_date,
    fte         = s.fte,
    status      = s.status;

-- Placeholder member for calls handled by logins that are not on the roster
INSERT IGNORE INTO dim_agent (employee_id, login, agent_name, team, team_leader, site, status)
VALUES ('UNKNOWN', NULL, 'Unknown / not on roster', 'Unassigned', NULL, NULL, 'Unknown');
