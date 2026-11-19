-- 01_schema.sql: PostgreSQL schema for the Smart Campus Facility and Maintenance Platform.
-- Executed automatically by the postgres image on first start (empty volume).
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    full_name VARCHAR(120) NOT NULL,
    role VARCHAR(30) NOT NULL CHECK (role IN ('admin','facility_manager','technician','approver','faculty','student','sensor')),
    token_hash CHAR(64) NOT NULL UNIQUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE facilities (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    location VARCHAR(120) NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    restricted BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bookings (
    id BIGSERIAL PRIMARY KEY,
    facility_id BIGINT NOT NULL REFERENCES facilities(id),
    requester_id BIGINT NOT NULL REFERENCES users(id),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    purpose VARCHAR(200) NOT NULL,
    attendees INTEGER NOT NULL CHECK (attendees > 0),
    status VARCHAR(20) NOT NULL CHECK (status IN ('REQUESTED','APPROVED','CONFIRMED','IN_USE','COMPLETED','CANCELLED')),
    decision_note VARCHAR(200),
    last_actor_id BIGINT REFERENCES users(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_time > start_time)
);

-- Database-level guard: two active bookings of the same facility may never overlap in time.
ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
    EXCLUDE USING gist (facility_id WITH =, tstzrange(start_time, end_time, '[)') WITH &&)
    WHERE (status IN ('REQUESTED','APPROVED','CONFIRMED','IN_USE'));

CREATE TABLE tickets (
    id BIGSERIAL PRIMARY KEY,
    facility_id BIGINT REFERENCES facilities(id),
    reporter_id BIGINT REFERENCES users(id),
    source VARCHAR(10) NOT NULL CHECK (source IN ('USER','SENSOR')),
    title VARCHAR(120) NOT NULL,
    description VARCHAR(2000) NOT NULL DEFAULT '',
    category VARCHAR(30) NOT NULL CHECK (category IN ('ELECTRICAL','PLUMBING','HVAC','SAFETY','FURNITURE_FIXTURE','OTHER')),
    priority VARCHAR(10) NOT NULL CHECK (priority IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    status VARCHAR(20) NOT NULL CHECK (status IN ('INTAKE','ASSIGNED','INSPECTION','PENDING_WORK','RESOLVED','CLOSED')),
    assignee_id BIGINT REFERENCES users(id),
    inspection_notes VARCHAR(2000) NOT NULL DEFAULT '',
    resolution_notes VARCHAR(2000) NOT NULL DEFAULT '',
    triage_rules TEXT NOT NULL DEFAULT '[]',
    sla_due_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE sensor_events (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(120) NOT NULL UNIQUE,
    facility_id BIGINT NOT NULL REFERENCES facilities(id),
    sensor_type VARCHAR(20) NOT NULL CHECK (sensor_type IN ('TEMPERATURE','SMOKE_LEVEL')),
    reading NUMERIC(10,2) NOT NULL,
    breached BOOLEAN NOT NULL,
    ticket_id BIGINT REFERENCES tickets(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE integration_links (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES tickets(id),
    provider VARCHAR(40) NOT NULL,
    title VARCHAR(160) NOT NULL,
    external_ref VARCHAR(60),
    mode VARCHAR(30) NOT NULL,
    status VARCHAR(10) NOT NULL CHECK (status IN ('SYNCED','PENDING')),
    attempts INTEGER NOT NULL DEFAULT 1,
    last_error VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_keys (
    id BIGSERIAL PRIMARY KEY,
    scope_key VARCHAR(200) NOT NULL UNIQUE,
    endpoint VARCHAR(80) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    response_status INTEGER,
    response_body TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(30) NOT NULL,
    entity_id BIGINT NOT NULL,
    action VARCHAR(40) NOT NULL,
    actor_id BIGINT REFERENCES users(id),
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bookings_facility_time ON bookings (facility_id, start_time, end_time);
CREATE INDEX idx_tickets_status_priority ON tickets (status, priority);
CREATE INDEX idx_audit_entity ON audit_events (entity_type, entity_id);
