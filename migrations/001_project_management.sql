-- 项目管理和需求索引表
-- Migration: 001_project_management
-- Created: 2026-04-22

-- 项目表
CREATE TABLE IF NOT EXISTS projects (
    project_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    repo_url VARCHAR(512),
    default_branch VARCHAR(64) DEFAULT 'main',
    created_by VARCHAR(128),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(32) DEFAULT 'active' CHECK (status IN ('active', 'archived', 'paused')),

    -- 统计字段（可以通过聚合查询计算，但缓存在这里提高性能）
    total_requirements INTEGER DEFAULT 0,
    total_cost_usd DECIMAL(10, 4) DEFAULT 0.0
);

-- 需求索引表
CREATE TABLE IF NOT EXISTS requirements (
    req_id VARCHAR(128) PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    workflow_id VARCHAR(256) NOT NULL,

    -- 基本信息
    title VARCHAR(512) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 状态信息
    lifecycle_state VARCHAR(32) DEFAULT 'draft' CHECK (lifecycle_state IN (
        'draft', 'in_progress', 'captured', 'prd_generated',
        'approved', 'released', 'closed', 'cancelled', 'paused', 'budget_exceeded'
    )),
    current_phase VARCHAR(16) DEFAULT 'P0',

    -- 成本和风险
    cost_used_usd DECIMAL(10, 4) DEFAULT 0.0,
    cost_cap_usd DECIMAL(10, 4) DEFAULT 20.0,
    risk_level VARCHAR(32) DEFAULT 'low' CHECK (risk_level IN ('low', 'medium', 'high', 'release-critical')),

    -- 交付物
    prd_path VARCHAR(512),
    commit_sha VARCHAR(64),
    commit_url VARCHAR(512),

    -- 摘要信息（用于快速展示）
    summary TEXT,
    ac_count INTEGER DEFAULT 0
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_requirements_project_id ON requirements(project_id);
CREATE INDEX IF NOT EXISTS idx_requirements_created_by ON requirements(created_by);
CREATE INDEX IF NOT EXISTS idx_requirements_lifecycle_state ON requirements(lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_requirements_created_at ON requirements(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_requirements_workflow_id ON requirements(workflow_id);

-- 更新时间触发器
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_requirements_updated_at BEFORE UPDATE ON requirements
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 初始化默认项目
INSERT INTO projects (project_id, name, description, repo_url, created_by)
VALUES
    ('healthassit', 'HealthAssit', '健康助手项目', 'https://github.com/qiurenjian/HealthAssit.git', 'system'),
    ('aioperator', 'AIOperator', 'AI运营助手系统', 'https://github.com/qiurenjian/AIOperator.git', 'system')
ON CONFLICT (project_id) DO NOTHING;
