-- ST FAMILY License Key System Database (PostgreSQL)

CREATE TABLE IF NOT EXISTS licenses (
    id SERIAL PRIMARY KEY,
    license_key VARCHAR(50) UNIQUE NOT NULL,
    hwid VARCHAR(100) DEFAULT NULL,
    expiry_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP DEFAULT NULL,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'banned', 'expired')),
    notes TEXT DEFAULT NULL,
    key_type VARCHAR(20) DEFAULT 'standard' CHECK (key_type IN ('standard', 'global_day', 'global_week', 'global_month'))
);

CREATE INDEX idx_license_key ON licenses(license_key);
CREATE INDEX idx_hwid ON licenses(hwid);
CREATE INDEX idx_status ON licenses(status);

-- Server settings table
CREATE TABLE IF NOT EXISTS server_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default settings
INSERT INTO server_settings (key, value) VALUES 
    ('server_enabled', '1'),
    ('key_validation_enabled', '1'),
    ('key_creation_enabled', '1')
ON CONFLICT (key) DO NOTHING;

-- Admin table
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    telegram_id BIGINT UNIQUE,
    password_hash VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default admin
INSERT INTO admins (username, telegram_id) 
VALUES ('admin', 7210704553)
ON CONFLICT (telegram_id) DO NOTHING;

-- Activity log
CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    action VARCHAR(100) NOT NULL,
    details TEXT,
    performed_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- View for active licenses
CREATE OR REPLACE VIEW active_licenses AS
SELECT 
    license_key,
    hwid,
    expiry_date,
    created_at,
    last_used,
    key_type,
    EXTRACT(DAY FROM (expiry_date - NOW())) as days_remaining
FROM licenses
WHERE status = 'active' AND expiry_date > NOW();
