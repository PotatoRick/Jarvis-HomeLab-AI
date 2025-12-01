-- Migration: v3.2.0 - Add target_host column and enhanced pattern support
-- Date: 2025-11-30
-- Purpose: Allow patterns to specify which host to execute commands on,
--          independent of where the alert's instance label points.

-- Add target_host column if it doesn't exist
ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS target_host VARCHAR(50);

-- Add missing columns that may not exist in older installations
ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS risk_level VARCHAR(10) DEFAULT 'low';

ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS usage_count INT DEFAULT 0;

ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS avg_execution_time FLOAT;

ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT true;

ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();

ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- Rename columns if they exist with old names (safe to run multiple times)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='remediation_patterns' AND column_name='last_used') THEN
        ALTER TABLE remediation_patterns RENAME COLUMN last_used TO last_used_at;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='remediation_patterns' AND column_name='last_updated') THEN
        ALTER TABLE remediation_patterns RENAME COLUMN last_updated TO updated_at;
    END IF;
END $$;

-- Delete old BackupStale patterns to replace with new ones
DELETE FROM remediation_patterns
WHERE alert_name = 'BackupStale' AND created_by = 'seed';

DELETE FROM remediation_patterns
WHERE alert_name = 'BackupHealthCheckStale' AND created_by = 'seed';

-- Insert new backup patterns with explicit target_host
INSERT INTO remediation_patterns (
    alert_name, alert_category, symptom_fingerprint, root_cause,
    solution_commands, target_host, confidence_score, created_by, metadata
) VALUES
    -- Home Assistant backup (most common case from today's issue)
    ('BackupStale', 'backup', 'BackupStale|system:homeassistant',
     'Home Assistant backup script did not run or failed to upload to B2. Scripts run on Skynet, not Nexus.',
     ARRAY['/home/t1/homelab/scripts/backup/backup_homeassistant_notify.sh'],
     'skynet',
     0.90, 'seed', '{"description": "Runs HA backup script on Skynet. Alert comes from Nexus metrics but fix runs on Skynet."}'::jsonb),

    -- Nexus backup
    ('BackupStale', 'backup', 'BackupStale|system:nexus',
     'Nexus backup script did not run or failed',
     ARRAY['cd /home/jordan/docker/home-stack && ./backup.sh'],
     'nexus',
     0.85, 'seed', '{"description": "Runs Nexus backup script locally"}'::jsonb),

    -- Skynet backup
    ('BackupStale', 'backup', 'BackupStale|system:skynet',
     'Skynet backup script did not run or failed',
     ARRAY['/home/t1/homelab/scripts/backup/backup_skynet.sh'],
     'skynet',
     0.85, 'seed', '{"description": "Runs Skynet backup script locally"}'::jsonb),

    -- Outpost backup
    ('BackupStale', 'backup', 'BackupStale|system:outpost',
     'Outpost backup script did not run or failed',
     ARRAY['cd /opt/burrow && ./backup.sh'],
     'outpost',
     0.85, 'seed', '{"description": "Runs Outpost backup script locally"}'::jsonb),

    -- Backup health check (cron job monitoring)
    ('BackupHealthCheckStale', 'monitoring', 'BackupHealthCheckStale|category:monitoring',
     'Backup health check cron job is not running on Skynet',
     ARRAY['/home/t1/homelab/scripts/backup/check_b2_backups.sh'],
     'skynet',
     0.85, 'seed', '{"description": "Runs backup check on Skynet and pushes metrics to Nexus"}'::jsonb)

ON CONFLICT (alert_name, symptom_fingerprint) DO UPDATE SET
    root_cause = EXCLUDED.root_cause,
    solution_commands = EXCLUDED.solution_commands,
    target_host = EXCLUDED.target_host,
    confidence_score = EXCLUDED.confidence_score,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

-- Show current patterns for verification
SELECT alert_name, symptom_fingerprint, target_host, confidence_score
FROM remediation_patterns
WHERE alert_name LIKE 'Backup%'
ORDER BY alert_name, symptom_fingerprint;
