-- Jarvis Database Initialization Script
-- This script creates all necessary tables for the AI remediation service

-- ============================================================================
-- EXISTING SCHEMA: Remediation Logs
-- ============================================================================

CREATE TABLE IF NOT EXISTS remediation_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    alert_name VARCHAR(255),
    alert_instance VARCHAR(255),
    alert_fingerprint VARCHAR(255),  -- Unique identifier from Alertmanager
    severity VARCHAR(50),
    alert_labels JSONB,
    alert_annotations JSONB,
    attempt_number INT,
    ai_analysis TEXT,
    ai_reasoning TEXT,
    remediation_plan TEXT,
    commands_executed TEXT[],
    command_outputs TEXT[],
    exit_codes INT[],
    success BOOLEAN,
    error_message TEXT,
    execution_duration_seconds INT,
    risk_level VARCHAR(10),
    escalated BOOLEAN,
    user_approved BOOLEAN,
    discord_message_id VARCHAR(50),
    discord_thread_id VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_remediation_log_timestamp ON remediation_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_remediation_log_alert_name ON remediation_log(alert_name);
CREATE INDEX IF NOT EXISTS idx_remediation_log_instance ON remediation_log(alert_instance);
CREATE INDEX IF NOT EXISTS idx_remediation_log_success ON remediation_log(success) WHERE success = true;


-- ============================================================================
-- NEW SCHEMA: Machine Learning / Knowledge Base
-- ============================================================================

-- Store successful remediation patterns that Jarvis learns over time
CREATE TABLE IF NOT EXISTS remediation_patterns (
    id SERIAL PRIMARY KEY,
    alert_name VARCHAR(255) NOT NULL,
    alert_category VARCHAR(100),          -- 'containers', 'network', 'database', 'system', etc.
    symptom_fingerprint TEXT,             -- Normalized description of the problem
    root_cause TEXT,                      -- What actually caused the issue
    solution_commands TEXT[],             -- Commands that successfully resolved it
    target_host VARCHAR(50),              -- Override: which host to execute on (service-host, ha-host, vps-host, management-host)
    success_count INT DEFAULT 1,          -- How many times this pattern worked
    failure_count INT DEFAULT 0,          -- How many times it failed
    avg_resolution_time INT,              -- Average seconds to resolve
    confidence_score FLOAT DEFAULT 0.80,  -- success/(success+failure)
    risk_level VARCHAR(10) DEFAULT 'low', -- Risk level: low, medium, high
    usage_count INT DEFAULT 0,            -- How many times pattern was used
    avg_execution_time FLOAT,             -- Average execution time in seconds
    first_seen TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    last_updated TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    created_by VARCHAR(50) DEFAULT 'learned',  -- 'claude', 'learned', 'seed'
    enabled BOOLEAN DEFAULT true,         -- Allow disabling patterns without deleting
    metadata JSONB,                       -- Additional context (host, service type, etc.)
    UNIQUE(alert_name, symptom_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_patterns_alert_name ON remediation_patterns(alert_name);
CREATE INDEX IF NOT EXISTS idx_patterns_confidence ON remediation_patterns(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_patterns_category ON remediation_patterns(alert_category);
CREATE INDEX IF NOT EXISTS idx_patterns_last_used ON remediation_patterns(last_used_at DESC);


-- Track alert fingerprints for pattern matching and similarity detection
CREATE TABLE IF NOT EXISTS alert_fingerprints (
    id SERIAL PRIMARY KEY,
    alert_name VARCHAR(255),
    instance VARCHAR(255),
    fingerprint_hash VARCHAR(64),         -- SHA256 of normalized alert data
    labels_summary JSONB,
    annotations_summary JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fingerprints_hash ON alert_fingerprints(fingerprint_hash);
CREATE INDEX IF NOT EXISTS idx_fingerprints_alert_name ON alert_fingerprints(alert_name);


-- Track learning feedback loop for continuous improvement
CREATE TABLE IF NOT EXISTS learning_feedback (
    id SERIAL PRIMARY KEY,
    remediation_log_id INT REFERENCES remediation_log(id) ON DELETE CASCADE,
    pattern_id INT REFERENCES remediation_patterns(id) ON DELETE CASCADE,
    used_learned_solution BOOLEAN,
    outcome VARCHAR(20),                  -- 'success', 'failure', 'partial'
    feedback_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_pattern ON learning_feedback(pattern_id);
CREATE INDEX IF NOT EXISTS idx_feedback_outcome ON learning_feedback(outcome);


-- ============================================================================
-- NEW SCHEMA: Host Monitoring
-- ============================================================================

-- Track host availability status for intelligent routing
CREATE TABLE IF NOT EXISTS host_status_log (
    id SERIAL PRIMARY KEY,
    host_name VARCHAR(50) NOT NULL,       -- 'service-host', 'ha-host', 'vps-host'
    status VARCHAR(20) NOT NULL,          -- 'ONLINE', 'OFFLINE', 'CHECKING'
    failure_count INT DEFAULT 0,
    last_successful_connection TIMESTAMP,
    last_check_attempt TIMESTAMP DEFAULT NOW(),
    error_message TEXT,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_host_status_name ON host_status_log(host_name);
CREATE INDEX IF NOT EXISTS idx_host_status_timestamp ON host_status_log(last_check_attempt DESC);


-- ============================================================================
-- NEW SCHEMA: Maintenance Windows
-- ============================================================================

-- Track scheduled and active maintenance windows for alert suppression
CREATE TABLE IF NOT EXISTS maintenance_windows (
    id SERIAL PRIMARY KEY,
    host VARCHAR(50),                     -- 'service-host', 'vps-host', 'ha-host', 'all'
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    reason TEXT,
    created_by VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    suppressed_alert_count INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_maintenance_active ON maintenance_windows(is_active, host) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_maintenance_started ON maintenance_windows(started_at DESC);


-- ============================================================================
-- NEW SCHEMA: Escalation Cooldowns (v3.1.0)
-- ============================================================================

-- Track escalation cooldowns to prevent Discord spam
-- When an alert is escalated, we record the time. If the same alert fires again
-- within the cooldown period (default 4 hours), we skip re-escalating.
-- When an alert resolves, we clear its cooldown so new incidents get escalated.
CREATE TABLE IF NOT EXISTS escalation_cooldowns (
    id SERIAL PRIMARY KEY,
    alert_name VARCHAR(255) NOT NULL,
    alert_instance VARCHAR(255) NOT NULL,
    escalated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(alert_name, alert_instance)
);

CREATE INDEX IF NOT EXISTS idx_escalation_cooldowns_alert ON escalation_cooldowns(alert_name, alert_instance);
CREATE INDEX IF NOT EXISTS idx_escalation_cooldowns_time ON escalation_cooldowns(escalated_at DESC);


-- ============================================================================
-- NEW SCHEMA: Alert Fingerprint Cache (v3.1.0)
-- ============================================================================

-- In-memory cache is preferred, but this table provides persistence across restarts
-- and allows multiple Jarvis instances to share deduplication state
CREATE TABLE IF NOT EXISTS alert_processing_cache (
    id SERIAL PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL UNIQUE,
    alert_name VARCHAR(255),
    alert_instance VARCHAR(255),
    processed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_cache_fingerprint ON alert_processing_cache(fingerprint);
CREATE INDEX IF NOT EXISTS idx_alert_cache_time ON alert_processing_cache(processed_at DESC);


-- ============================================================================
-- NEW SCHEMA: Remediation Failures (Phase 1 - Self-Sufficiency Roadmap)
-- ============================================================================

-- Track failed remediation patterns to avoid repeating mistakes
-- This helps Jarvis learn what NOT to do
CREATE TABLE IF NOT EXISTS remediation_failures (
    id SERIAL PRIMARY KEY,
    alert_name VARCHAR(255) NOT NULL,
    alert_instance VARCHAR(255),
    pattern_signature VARCHAR(64) NOT NULL UNIQUE,
    symptom_fingerprint TEXT,
    commands_attempted TEXT[],
    failure_reason TEXT,
    failure_count INTEGER DEFAULT 1,
    last_failed_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_failures_alert ON remediation_failures(alert_name);
CREATE INDEX IF NOT EXISTS idx_failures_signature ON remediation_failures(pattern_signature);
CREATE INDEX IF NOT EXISTS idx_failures_time ON remediation_failures(last_failed_at DESC);


-- ============================================================================
-- SEED DATA: Bootstrap with common patterns
-- ============================================================================

INSERT INTO remediation_patterns (
    alert_name, alert_category, symptom_fingerprint, root_cause,
    solution_commands, confidence_score, created_by, metadata
) VALUES
    -- Container health patterns
    ('ContainerUnhealthy', 'containers', 'docker_healthcheck_failing',
     'Container healthcheck command failing',
     ARRAY['docker restart {container}'],
     0.85, 'seed', '{"typical_resolution_time": 10}'::jsonb),

    ('ContainerDown', 'containers', 'container_not_running',
     'Container stopped or crashed',
     ARRAY['docker start {container}'],
     0.90, 'seed', '{"typical_resolution_time": 5}'::jsonb),

    ('ContainerRestartLoop', 'containers', 'continuous_restart',
     'Container crashing immediately after start',
     ARRAY['docker logs {container} --tail 50', 'docker inspect {container}'],
     0.60, 'seed', '{"requires_analysis": true}'::jsonb),

    -- Memory patterns
    ('HighMemoryUsage', 'system', 'memory_above_90_percent',
     'Memory usage critically high',
     ARRAY['docker restart {container}'],
     0.70, 'seed', '{"temporary_fix": true}'::jsonb),

    ('ContainerOOM', 'containers', 'out_of_memory_killed',
     'Container killed by OOM',
     ARRAY['docker restart {container}'],
     0.75, 'seed', '{"needs_memory_increase": true}'::jsonb),

    -- Database patterns
    ('PostgreSQLDown', 'database', 'postgres_unreachable',
     'PostgreSQL service not responding',
     ARRAY['sudo systemctl restart postgresql'],
     0.80, 'seed', '{"typical_resolution_time": 30}'::jsonb),

    ('DatabaseConnectionPoolExhausted', 'database', 'connection_pool_full',
     'Too many database connections',
     ARRAY['docker restart {container}'],
     0.75, 'seed', '{"typical_resolution_time": 15}'::jsonb),

    -- Network patterns
    ('ServiceUnreachable', 'network', 'http_check_failing',
     'HTTP endpoint not responding',
     ARRAY['docker restart {container}'],
     0.70, 'seed', '{"typical_resolution_time": 12}'::jsonb),

    ('WireGuardVPNDown', 'network', 'vpn_tunnel_down',
     'WireGuard tunnel disconnected',
     ARRAY['sudo systemctl restart wg-quick@wg0'],
     0.80, 'seed', '{"typical_resolution_time": 15}'::jsonb),

    -- Disk patterns
    ('DiskSpaceHigh', 'system', 'disk_above_85_percent',
     'Disk usage critically high',
     ARRAY['docker system prune -af --volumes'],
     0.65, 'seed', '{"can_free_space": true}'::jsonb),

    -- Certificate patterns
    ('TLSCertificateExpiringSoon', 'security', 'certificate_expiring',
     'TLS certificate expiring within 15 days',
     ARRAY['docker restart caddy'],
     0.85, 'seed', '{"triggers_renewal": true}'::jsonb),

    -- System patterns
    ('HighCPUUsage', 'system', 'cpu_above_90_percent',
     'CPU usage critically high',
     ARRAY['docker restart {container}'],
     0.60, 'seed', '{"temporary_fix": true}'::jsonb),

    ('SystemdServiceFailed', 'system', 'systemd_unit_failed',
     'Systemd service in failed state',
     ARRAY['sudo systemctl restart {service}'],
     0.80, 'seed', '{"typical_resolution_time": 10}'::jsonb),

    -- Prometheus/Monitoring patterns
    ('TargetDown', 'monitoring', 'prometheus_scrape_failing',
     'Prometheus cannot scrape metrics',
     ARRAY['docker restart {container}'],
     0.70, 'seed', '{"typical_resolution_time": 8}'::jsonb),

    -- Prometheus/Monitoring patterns (generic TargetDown above)
    -- Note: Backup patterns are inserted separately below with target_host column

    ('TargetDown', 'monitoring', 'prometheus_scrape_failing_generic',
     'Prometheus cannot scrape metrics from target',
     ARRAY['docker restart {container}'],
     0.70, 'seed', '{"typical_resolution_time": 8}'::jsonb)

ON CONFLICT (alert_name, symptom_fingerprint) DO NOTHING;

-- ============================================================================
-- BACKUP PATTERNS: Require target_host for system-specific remediation
-- ============================================================================
-- IMPORTANT: Backup metrics are scraped from Service-Host textfile collector, but scripts run on DIFFERENT hosts!
-- The 'system' label in the alert tells us WHICH backup is stale, and determines where to run the fix.
--
-- System        | Run Fix On | Script Path
-- --------------|------------|-------------
-- ha-host | management-host     | /home/<user>/homelab/scripts/backup/backup_ha-host_notify.sh
-- management-host        | management-host     | /home/<user>/homelab/scripts/backup/backup_management-host_notify.sh
-- service-host         | service-host      | /home/<user>/docker/backups/backup_notify.sh
-- vps-host       | vps-host    | /opt/<app>/backups/backup_vps_notify.sh

INSERT INTO remediation_patterns (
    alert_name, alert_category, symptom_fingerprint, root_cause,
    solution_commands, target_host, confidence_score, created_by, metadata
) VALUES
    ('BackupStale', 'backup', 'BackupStale|system:ha-host|category:backup',
     'Home Assistant backup script did not run or failed to upload to B2. Script runs on Management-Host, not Service-Host.',
     ARRAY['/home/<user>/homelab/scripts/backup/backup_ha-host_notify.sh'],
     'management-host', 0.90, 'seed',
     '{"description": "Runs HA backup script on Management-Host. Alert comes from Service-Host metrics but fix runs on Management-Host."}'::jsonb),

    ('BackupStale', 'backup', 'BackupStale|system:service-host|category:backup',
     'Service-Host backup script did not run or failed to upload to B2.',
     ARRAY['/home/<user>/docker/backups/backup_notify.sh'],
     'service-host', 0.85, 'seed',
     '{"description": "Runs Service-Host backup script locally on Service-Host."}'::jsonb),

    ('BackupStale', 'backup', 'BackupStale|system:management-host|category:backup',
     'Management-Host backup script did not run or failed to upload to B2.',
     ARRAY['/home/<user>/homelab/scripts/backup/backup_management-host_notify.sh'],
     'management-host', 0.85, 'seed',
     '{"description": "Runs Management-Host backup script locally."}'::jsonb),

    ('BackupStale', 'backup', 'BackupStale|system:vps-host|category:backup',
     'VPS-Host backup script did not run or failed to upload to B2.',
     ARRAY['/opt/<app>/backups/backup_vps_notify.sh'],
     'vps-host', 0.85, 'seed',
     '{"description": "Runs VPS-Host VPS backup script."}'::jsonb),

    ('BackupHealthCheckStale', 'monitoring', 'BackupHealthCheckStale|category:monitoring',
     'Backup health check cron job is not running on Management-Host. This script checks B2 for all backups and pushes metrics to Service-Host.',
     ARRAY['/home/<user>/homelab/scripts/backup/check_b2_backups.sh'],
     'management-host', 0.85, 'seed',
     '{"description": "Runs backup check on Management-Host and SCPs metrics to Service-Host textfile collector."}'::jsonb)

ON CONFLICT (alert_name, symptom_fingerprint) DO NOTHING;

-- ============================================================================
-- DATABASE FUNCTIONS: Helper utilities
-- ============================================================================

-- Function to calculate pattern confidence score
CREATE OR REPLACE FUNCTION calculate_pattern_confidence(success_count INT, failure_count INT, days_since_last_use INT)
RETURNS FLOAT AS $$
DECLARE
    base_score FLOAT;
    recency_bonus FLOAT;
    frequency_penalty FLOAT;
    final_score FLOAT;
BEGIN
    -- Base score: success rate
    IF (success_count + failure_count) = 0 THEN
        RETURN 0.5;
    END IF;

    base_score := success_count::FLOAT / (success_count + failure_count);

    -- Recency bonus: +10% if used in last 7 days
    IF days_since_last_use <= 7 THEN
        recency_bonus := 0.10;
    ELSE
        recency_bonus := 0.0;
    END IF;

    -- Frequency penalty: -5% if failures > 2
    IF failure_count > 2 THEN
        frequency_penalty := 0.05;
    ELSE
        frequency_penalty := 0.0;
    END IF;

    final_score := base_score + recency_bonus - frequency_penalty;

    -- Clamp between 0.3 and 0.95
    IF final_score < 0.3 THEN
        final_score := 0.3;
    ELSIF final_score > 0.95 THEN
        final_score := 0.95;
    END IF;

    RETURN final_score;
END;
$$ LANGUAGE plpgsql;

-- Function to get active maintenance windows for a host
CREATE OR REPLACE FUNCTION is_host_in_maintenance(host_name VARCHAR)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM maintenance_windows
        WHERE is_active = true
        AND (host = host_name OR host = 'all')
        AND (ended_at IS NULL OR ended_at > NOW())
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- VIEWS: Convenience queries
-- ============================================================================

-- View for high-confidence patterns
-- HIGH-004 FIX: Use correct column name (last_used_at instead of last_used)
CREATE OR REPLACE VIEW high_confidence_patterns AS
SELECT
    id,
    alert_name,
    alert_category,
    solution_commands,
    confidence_score,
    success_count,
    failure_count,
    avg_resolution_time,
    last_used_at
FROM remediation_patterns
WHERE confidence_score >= 0.75
ORDER BY confidence_score DESC, success_count DESC;

-- View for learning statistics
CREATE OR REPLACE VIEW learning_stats AS
SELECT
    COUNT(*) as total_patterns,
    COUNT(*) FILTER (WHERE confidence_score >= 0.75) as high_confidence_patterns,
    COUNT(*) FILTER (WHERE created_by = 'learned') as learned_patterns,
    COUNT(*) FILTER (WHERE created_by = 'seed') as seeded_patterns,
    AVG(confidence_score) as avg_confidence,
    SUM(success_count) as total_successes,
    SUM(failure_count) as total_failures
FROM remediation_patterns;

-- ============================================================================
-- NEW SCHEMA: Proactive Monitoring (Phase 3 - Self-Sufficiency Roadmap)
-- ============================================================================

-- Track proactive monitoring checks and findings
CREATE TABLE IF NOT EXISTS proactive_checks (
    id SERIAL PRIMARY KEY,
    check_type VARCHAR(50) NOT NULL,          -- 'disk_fill_rate', 'certificate_expiry', etc.
    target VARCHAR(255) NOT NULL,              -- Host, container, or service checked
    finding TEXT NOT NULL,                     -- What was found
    action_taken TEXT,                         -- What action was taken (if any)
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proactive_checks_type ON proactive_checks(check_type);
CREATE INDEX IF NOT EXISTS idx_proactive_checks_target ON proactive_checks(target);
CREATE INDEX IF NOT EXISTS idx_proactive_checks_time ON proactive_checks(created_at DESC);


-- ============================================================================
-- NEW SCHEMA: State Snapshots for Rollback (Phase 3 - Self-Sufficiency Roadmap)
-- ============================================================================

-- Store state snapshots before remediation for potential rollback
CREATE TABLE IF NOT EXISTS state_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_id VARCHAR(64) NOT NULL UNIQUE,
    host VARCHAR(50) NOT NULL,                -- 'service-host', 'ha-host', 'vps-host', 'management-host'
    target_type VARCHAR(20) NOT NULL,         -- 'container', 'service', 'config', 'database'
    target_name VARCHAR(255) NOT NULL,        -- Container name, service name, etc.
    state_data TEXT,                          -- JSON blob of captured state
    alert_context TEXT,                       -- Alert that triggered snapshot
    rolled_back_at TIMESTAMP,                 -- When rollback was performed (NULL if not rolled back)
    rollback_reason TEXT,                     -- Why rollback was performed
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_id ON state_snapshots(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_host ON state_snapshots(host);
CREATE INDEX IF NOT EXISTS idx_snapshots_target ON state_snapshots(target_type, target_name);
CREATE INDEX IF NOT EXISTS idx_snapshots_time ON state_snapshots(created_at DESC);


-- ============================================================================
-- NEW SCHEMA: n8n Workflow Executions (Phase 3 - Self-Sufficiency Roadmap)
-- ============================================================================

-- Track n8n workflow executions triggered by Jarvis
CREATE TABLE IF NOT EXISTS n8n_executions (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(100) NOT NULL,
    workflow_name VARCHAR(255),
    execution_id VARCHAR(100),
    alert_name VARCHAR(255),                  -- Alert that triggered workflow
    alert_instance VARCHAR(255),
    input_data JSONB,                         -- Data passed to workflow
    status VARCHAR(20),                       -- 'started', 'success', 'failed', 'timeout'
    output_data JSONB,                        -- Response from workflow
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_n8n_workflow ON n8n_executions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_n8n_execution_id ON n8n_executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_n8n_status ON n8n_executions(status);
CREATE INDEX IF NOT EXISTS idx_n8n_time ON n8n_executions(started_at DESC);


-- ============================================================================
-- NEW SCHEMA: Self-Preservation Handoffs (Phase 5 - Self-Restart Capability)
-- ============================================================================

-- Track self-restart handoffs to n8n for safe restarts of Jarvis and dependencies
-- This table MUST survive restarts since it's the source of truth for resume operations
CREATE TABLE IF NOT EXISTS self_preservation_handoffs (
    id SERIAL PRIMARY KEY,
    handoff_id VARCHAR(64) NOT NULL UNIQUE,
    restart_target VARCHAR(50) NOT NULL,          -- 'jarvis', 'postgres-jarvis', 'docker-daemon', 'management-host-host'
    restart_reason TEXT NOT NULL,
    remediation_context TEXT,                     -- JSON blob of serialized RemediationContext
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending', 'in_progress', 'completed', 'failed', 'timeout', 'cancelled'
    callback_url VARCHAR(500) NOT NULL,
    n8n_execution_id VARCHAR(100),
    error_message TEXT,
    created_at VARCHAR(50) NOT NULL,              -- ISO format timestamp string
    completed_at VARCHAR(50)                      -- ISO format timestamp string
);

CREATE INDEX IF NOT EXISTS idx_sp_handoff_id ON self_preservation_handoffs(handoff_id);
CREATE INDEX IF NOT EXISTS idx_sp_status ON self_preservation_handoffs(status);
CREATE INDEX IF NOT EXISTS idx_sp_created ON self_preservation_handoffs(created_at DESC);

-- Only allow one pending or in-progress handoff at a time
-- This prevents multiple concurrent self-restarts
CREATE UNIQUE INDEX IF NOT EXISTS idx_sp_active_handoff
    ON self_preservation_handoffs(status)
    WHERE status IN ('pending', 'in_progress');


-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO jarvis;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO jarvis;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO jarvis;
