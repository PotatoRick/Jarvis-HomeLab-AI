-- Migration: v3.8.1 - Fix BackupStale patterns with correct paths and target_host
-- Date: 2025-12-06
-- Issue: BackupStale alerts failing with exit code 127 due to wrong script paths
--
-- This migration:
-- 1. Deletes old BackupStale patterns with incorrect paths
-- 2. Inserts new patterns with correct paths and target_host column populated
-- 3. Clears any failed remediation patterns for BackupStale
--
-- Run with: docker exec -i postgres-jarvis psql -U jarvis -d jarvis < migrations/v3.8.1_fix_backup_patterns.sql

BEGIN;

-- ============================================================================
-- Step 1: Delete old incorrect BackupStale patterns
-- ============================================================================
DELETE FROM remediation_patterns
WHERE alert_name = 'BackupStale'
AND created_by = 'seed';

DELETE FROM remediation_patterns
WHERE alert_name = 'BackupHealthCheckStale'
AND created_by = 'seed';

-- Also delete any learned patterns for BackupStale that have wrong paths
DELETE FROM remediation_patterns
WHERE alert_name = 'BackupStale'
AND (
    solution_commands @> ARRAY['/home/<user>/homelab/scripts/backup/backup_skynet.sh']
    OR solution_commands @> ARRAY['cd /opt/burrow && ./backup.sh']
    OR solution_commands @> ARRAY['cd /home/<user>/docker/home-stack && ./backup.sh']
);

-- ============================================================================
-- Step 2: Clear failed remediation patterns for BackupStale (if table exists)
-- ============================================================================
-- These failures were caused by wrong paths, so clear them to give fresh start
-- Note: remediation_failures table may not exist in older databases
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'remediation_failures') THEN
        DELETE FROM remediation_failures WHERE alert_name = 'BackupStale';
        DELETE FROM remediation_failures WHERE alert_name = 'BackupHealthCheckStale';
        RAISE NOTICE 'Cleared BackupStale failure patterns';
    ELSE
        RAISE NOTICE 'remediation_failures table does not exist, skipping cleanup';
    END IF;
END $$;

-- ============================================================================
-- Step 3: Insert corrected BackupStale patterns with target_host column
-- ============================================================================

INSERT INTO remediation_patterns (
    alert_name,
    alert_category,
    symptom_fingerprint,
    root_cause,
    solution_commands,
    target_host,
    confidence_score,
    risk_level,
    created_by,
    metadata
) VALUES
    -- Home Assistant backup (runs on Skynet)
    ('BackupStale', 'backup', 'BackupStale|system:homeassistant|category:backup',
     'Home Assistant backup script did not run or failed to upload to B2. Script runs on Skynet, not Nexus.',
     ARRAY['/home/<user>/homelab/scripts/backup/backup_homeassistant_notify.sh'],
     'skynet', 0.90, 'low', 'seed',
     '{"description": "Runs HA backup script on Skynet. Alert comes from Nexus metrics but fix runs on Skynet."}'::jsonb),

    -- Nexus backup (runs on Nexus)
    ('BackupStale', 'backup', 'BackupStale|system:nexus|category:backup',
     'Nexus backup script did not run or failed to upload to B2.',
     ARRAY['/home/<user>/docker/backups/backup_notify.sh'],
     'nexus', 0.85, 'low', 'seed',
     '{"description": "Runs Nexus backup script locally on Nexus."}'::jsonb),

    -- Skynet backup (runs on Skynet)
    ('BackupStale', 'backup', 'BackupStale|system:skynet|category:backup',
     'Skynet backup script did not run or failed to upload to B2.',
     ARRAY['/home/<user>/homelab/scripts/backup/backup_skynet_notify.sh'],
     'skynet', 0.85, 'low', 'seed',
     '{"description": "Runs Skynet backup script locally."}'::jsonb),

    -- Outpost backup (runs on Outpost)
    ('BackupStale', 'backup', 'BackupStale|system:outpost|category:backup',
     'Outpost backup script did not run or failed to upload to B2.',
     ARRAY['/opt/<app>/backups/backup_vps_notify.sh'],
     'outpost', 0.85, 'low', 'seed',
     '{"description": "Runs Outpost VPS backup script."}'::jsonb),

    -- Backup health check (always runs on Skynet)
    ('BackupHealthCheckStale', 'monitoring', 'BackupHealthCheckStale|category:monitoring',
     'Backup health check cron job is not running on Skynet. This script checks B2 for all backups and pushes metrics to Nexus.',
     ARRAY['/home/<user>/homelab/scripts/backup/check_b2_backups.sh'],
     'skynet', 0.85, 'low', 'seed',
     '{"description": "Runs backup check on Skynet and SCPs metrics to Nexus textfile collector."}'::jsonb)

ON CONFLICT (alert_name, symptom_fingerprint) DO UPDATE SET
    root_cause = EXCLUDED.root_cause,
    solution_commands = EXCLUDED.solution_commands,
    target_host = EXCLUDED.target_host,
    confidence_score = EXCLUDED.confidence_score,
    updated_at = NOW();

-- ============================================================================
-- Step 4: Verify the migration
-- ============================================================================
DO $$
DECLARE
    pattern_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO pattern_count
    FROM remediation_patterns
    WHERE alert_name = 'BackupStale'
    AND target_host IS NOT NULL;

    IF pattern_count < 4 THEN
        RAISE EXCEPTION 'Migration verification failed: Expected 4 BackupStale patterns with target_host, found %', pattern_count;
    END IF;

    RAISE NOTICE 'Migration successful: % BackupStale patterns with target_host column populated', pattern_count;
END $$;

COMMIT;

-- Show the results
SELECT
    alert_name,
    symptom_fingerprint,
    target_host,
    solution_commands[1] as script_path,
    confidence_score
FROM remediation_patterns
WHERE alert_name IN ('BackupStale', 'BackupHealthCheckStale')
ORDER BY alert_name, symptom_fingerprint;
