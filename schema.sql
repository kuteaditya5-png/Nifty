CREATE TABLE IF NOT EXISTS app_users (
    user_id BIGSERIAL PRIMARY KEY,
    mobile_number VARCHAR(20) UNIQUE NOT NULL,
    is_mobile_verified BOOLEAN NOT NULL DEFAULT FALSE,
    whatsapp_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS fo_alert_settings (
    alert_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    alert_time TIME,
    alert_type VARCHAR(10) NOT NULL DEFAULT 'BOTH',
    min_confidence NUMERIC(5,2) NOT NULL DEFAULT 70,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_fo_alert_settings_user_active
ON fo_alert_settings(user_id)
WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS fo_alert_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES app_users(user_id) ON DELETE SET NULL,
    signal VARCHAR(20),
    nifty_price NUMERIC(12,2),
    strike_price NUMERIC(12,2),
    option_type VARCHAR(5),
    entry_price NUMERIC(12,2),
    stop_loss NUMERIC(12,2),
    target1 NUMERIC(12,2),
    target2 NUMERIC(12,2),
    confidence NUMERIC(5,2),
    whatsapp_status VARCHAR(40),
    message_sid VARCHAR(80),
    signal_key VARCHAR(160),
    sent_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_alert_history_user_sent
ON fo_alert_history(user_id, sent_at DESC);
