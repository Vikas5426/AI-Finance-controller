-- PostgreSQL Initialization Script for Recon
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Ensure database user has full schema permissions
GRANT ALL PRIVILEGES ON DATABASE finance_controller TO postgres;
