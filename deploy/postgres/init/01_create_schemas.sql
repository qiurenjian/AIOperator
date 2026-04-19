-- AIOperator Postgres 初始化脚本
-- 由 docker-compose 在首次启动 postgres 容器时自动执行
-- 注意：仅在 data volume 为空时执行一次

-- 1. 创建 temporal 元数据库与用户
CREATE USER temporal WITH PASSWORD 'changeme_temporal_pw';
CREATE DATABASE temporal OWNER temporal;
CREATE DATABASE temporal_visibility OWNER temporal;

-- 2. 在 aiop 业务库内创建 schema 隔离
\c aiop
CREATE SCHEMA IF NOT EXISTS aiop AUTHORIZATION aiop;

-- 3. 时区与扩展
SET timezone = 'Asia/Shanghai';
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 真正的表结构由 db/migrations/ 用 alembic 管理，此处不建表。
