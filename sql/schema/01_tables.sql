-- =====================================================================
-- Core schema: audit log, dimensions, facts.
-- Idempotent: safe to run on every pipeline start.
-- Staging tables (stg_*) are created by the loader each run.
-- =====================================================================

CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id           INT AUTO_INCREMENT PRIMARY KEY,
    reporting_month  CHAR(7)       NOT NULL,
    started_at       DATETIME      NOT NULL,
    finished_at      DATETIME      NULL,
    status           VARCHAR(20)   NOT NULL,          -- RUNNING / SUCCESS / FAILED
    rows_loaded      INT           NULL,
    rows_rejected    INT           NULL,
    message          VARCHAR(2000) NULL,
    INDEX ix_run_month (reporting_month, status)
);

CREATE TABLE IF NOT EXISTS ref_public_holiday (
    holiday_date  DATE        PRIMARY KEY,
    holiday_name  VARCHAR(60) NOT NULL,
    state         CHAR(3)     NOT NULL DEFAULT 'QLD'
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_key           INT         PRIMARY KEY,           -- yyyymmdd
    full_date          DATE        NOT NULL UNIQUE,
    year_num           SMALLINT    NOT NULL,
    month_num          TINYINT     NOT NULL,
    month_name         VARCHAR(10) NOT NULL,
    month_start        DATE        NOT NULL,
    reporting_month    CHAR(7)     NOT NULL,
    week_start         DATE        NOT NULL,              -- Monday
    day_of_month       TINYINT     NOT NULL,
    day_of_week        TINYINT     NOT NULL,              -- 1 = Monday
    day_name           VARCHAR(10) NOT NULL,
    is_weekend         TINYINT     NOT NULL,
    is_public_holiday  TINYINT     NOT NULL DEFAULT 0,
    holiday_name       VARCHAR(60) NULL
);

CREATE TABLE IF NOT EXISTS dim_queue (
    queue_id        VARCHAR(40)  PRIMARY KEY,
    brand           VARCHAR(30)  NOT NULL,
    queue_function  VARCHAR(30)  NOT NULL,
    sl_target_sec   SMALLINT     NOT NULL,
    sl_target_pct   DECIMAL(4,3) NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_agent (
    employee_id   VARCHAR(10)  PRIMARY KEY,
    login         VARCHAR(60)  NULL,
    agent_name    VARCHAR(80)  NOT NULL,
    team          VARCHAR(30)  NOT NULL,
    team_leader   VARCHAR(60)  NULL,
    site          VARCHAR(40)  NULL,
    start_date    DATE         NULL,
    end_date      DATE         NULL,
    fte           DECIMAL(4,2) NULL,
    status        VARCHAR(20)  NOT NULL,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- One row per inbound call offered to a queue
CREATE TABLE IF NOT EXISTS fact_call (
    interaction_id    CHAR(36)     PRIMARY KEY,
    reporting_month   CHAR(7)      NOT NULL,
    date_key          INT          NOT NULL,
    call_date         DATE         NOT NULL,
    start_ts_local    DATETIME     NOT NULL,              -- Australia/Brisbane
    hour_of_day       TINYINT      NOT NULL,
    queue_id          VARCHAR(40)  NOT NULL,
    employee_id       VARCHAR(10)  NULL,                  -- NULL when abandoned
    is_answered       TINYINT      NOT NULL,
    is_abandoned      TINYINT      NOT NULL,
    is_short_abandon  TINYINT      NOT NULL,              -- abandoned in < 5 seconds
    wait_sec          INT          NOT NULL,
    talk_sec          INT          NOT NULL,
    hold_sec          INT          NOT NULL,
    acw_sec           INT          NOT NULL,
    handle_sec        INT          NOT NULL,              -- talk + hold + after-call work
    is_transferred    TINYINT      NOT NULL,
    answered_in_sl    TINYINT      NOT NULL,              -- answered within the queue's SL threshold
    INDEX ix_call_month (reporting_month),
    INDEX ix_call_date (call_date, queue_id),
    INDEX ix_call_agent (employee_id, reporting_month)
);

-- One row per CRM case (a logged interaction on an answered call)
CREATE TABLE IF NOT EXISTS fact_interaction (
    case_id           VARCHAR(20)   PRIMARY KEY,
    interaction_id    CHAR(36)      NULL,
    reporting_month   CHAR(7)       NOT NULL,
    created_ts_local  DATETIME      NOT NULL,
    call_date         DATE          NOT NULL,
    employee_id       VARCHAR(10)   NULL,
    brand             VARCHAR(30)   NOT NULL,
    policy_number     VARCHAR(20)   NULL,
    contact_reason    VARCHAR(60)   NOT NULL,
    outcome           VARCHAR(40)   NOT NULL,
    is_sale           TINYINT       NOT NULL,
    product           VARCHAR(40)   NULL,
    annual_premium    DECIMAL(10,2) NULL,
    INDEX ix_int_month (reporting_month),
    INDEX ix_int_policy (policy_number, created_ts_local),
    INDEX ix_int_call (interaction_id)
);

-- One row per (deduplicated) post-call survey response
CREATE TABLE IF NOT EXISTS fact_survey (
    response_id        VARCHAR(20)  PRIMARY KEY,
    interaction_id     CHAR(36)     NOT NULL,
    reporting_month    CHAR(7)      NOT NULL,             -- month the response was received
    response_ts_local  DATETIME     NOT NULL,
    csat               TINYINT      NULL,                 -- 1-5
    nps                TINYINT      NULL,                 -- 0-10
    fcr_self_reported  TINYINT      NULL,
    verbatim           VARCHAR(500) NULL,
    INDEX ix_srv_month (reporting_month),
    INDEX ix_srv_call (interaction_id)
);

-- WFM daily forecast by queue
CREATE TABLE IF NOT EXISTS fact_forecast (
    forecast_date     DATE        NOT NULL,
    queue_id          VARCHAR(40) NOT NULL,
    reporting_month   CHAR(7)     NOT NULL,
    forecast_offered  INT         NOT NULL,
    forecast_aht_sec  INT         NOT NULL,
    scheduled_hours   DECIMAL(7,1) NOT NULL,
    PRIMARY KEY (forecast_date, queue_id)
);
