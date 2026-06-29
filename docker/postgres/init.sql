-- VisionMart - PostgreSQL bootstrap
-- Database and role are created by the official postgres image via env vars.
-- This file is reserved for future extensions and one-time setup.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Concrete schemas and tables are managed via Alembic migrations.
