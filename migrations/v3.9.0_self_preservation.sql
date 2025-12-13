-- Migration: v3.9.0 Self-Preservation Handoffs
-- Adds table for tracking self-restart handoffs to n8n
-- Run this migration on existing databases before upgrading to v3.9.0

-- ============================================================================
-- Self-Preservation Handoffs Table
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

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_sp_handoff_id ON self_preservation_handoffs(handoff_id);
CREATE INDEX IF NOT EXISTS idx_sp_status ON self_preservation_handoffs(status);
CREATE INDEX IF NOT EXISTS idx_sp_created ON self_preservation_handoffs(created_at DESC);

-- Only allow one pending or in-progress handoff at a time
-- This prevents multiple concurrent self-restarts
CREATE UNIQUE INDEX IF NOT EXISTS idx_sp_active_handoff
    ON self_preservation_handoffs(status)
    WHERE status IN ('pending', 'in_progress');

-- Grant permissions
GRANT ALL PRIVILEGES ON self_preservation_handoffs TO jarvis;
GRANT ALL PRIVILEGES ON self_preservation_handoffs_id_seq TO jarvis;

-- ============================================================================
-- Migration Complete
-- ============================================================================

-- Verify the table was created
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'self_preservation_handoffs') THEN
        RAISE NOTICE 'Migration v3.9.0: self_preservation_handoffs table created successfully';
    ELSE
        RAISE EXCEPTION 'Migration v3.9.0: Failed to create self_preservation_handoffs table';
    END IF;
END $$;
