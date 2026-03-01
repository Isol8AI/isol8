-- =============================================================================
-- Migration: Add containers table for ECS Fargate per-user services
-- =============================================================================
-- Run this against Supabase BEFORE deploying the new backend.
-- Execute once per schema (dev, staging, prod).
--
-- Usage:
--   SET search_path TO dev;  -- or staging, prod
--   \i migrations/001_add_containers_table.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS containers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL,
    service_name VARCHAR,
    task_arn VARCHAR,
    gateway_token VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'stopped',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One service per user
    CONSTRAINT uq_containers_user_id UNIQUE (user_id),

    -- Service names must be unique
    CONSTRAINT uq_containers_service_name UNIQUE (service_name),

    -- Gateway tokens must be unique
    CONSTRAINT idx_containers_gateway_token UNIQUE (gateway_token),

    -- Valid status values
    CONSTRAINT chk_container_status CHECK (
        status IN ('provisioning', 'running', 'stopped', 'error')
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_containers_user_id ON containers (user_id);
CREATE INDEX IF NOT EXISTS idx_containers_status ON containers (status);
