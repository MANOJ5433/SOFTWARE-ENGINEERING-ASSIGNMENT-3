-- 02_seed.sql: synthetic reference data for demonstration and testing.
-- Token hashes are SHA-256 of the demo tokens listed in README.md (demo credentials only).
INSERT INTO users (username, full_name, role, token_hash) VALUES
 ('admin', 'Campus Administrator', 'admin', 'b1953baf2deb0e98aab2b02925a2f5c0751c175f4bd732afaad4131e65e39483'),
 ('facmgr', 'Facility Manager', 'facility_manager', 'c3cc9751445cc1f2536ed03c5bdc2d36379b13a18a3e6609d817ac70f7a98034'),
 ('approver', 'Department Approver', 'approver', 'bcb99312b277222e833ffda0b2fa0eaf8d4d97dfd550ff4032d0cc9b8c5e9258'),
 ('tech1', 'Maintenance Technician One', 'technician', '8b31d69caa077c6e5cb9b7e1c7a4e37da53c689008767069228033961ce728ab'),
 ('tech2', 'Maintenance Technician Two', 'technician', '7bcaf433dbd25e5c30ace7f58785f74b00d913cdb1089da34095378e137de647'),
 ('faculty1', 'Faculty Member', 'faculty', '81cc44ccf929a7d07cfafc28a8a845eae96423c2fa1fdf46eba93cb405e7fd7d'),
 ('student1', 'Student Member', 'student', '676d5393d31fff706c24024c56412c4d77ae4f82bb28d4d39617c8952f5cdd42'),
 ('sensor-gw', 'Sensor Gateway', 'sensor', '6f9be293b9898701e1cd363b148903cdbf14fff65cc1f46dcddb24d350648c40')
ON CONFLICT (username) DO NOTHING;

INSERT INTO facilities (code, name, location, capacity, restricted) VALUES
 ('SEM-201', 'Seminar Room 201', 'Block B, Level 2', 30, FALSE),
 ('LAB-101', 'Computing Lab 101', 'Block A, Level 1', 40, TRUE),
 ('AUD-1', 'Main Auditorium', 'Central Block', 300, TRUE),
 ('LIB-RM2', 'Library Study Room 2', 'Library, Level 1', 8, FALSE),
 ('CHEM-LAB', 'Chemistry Lab', 'Science Block', 24, TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO bookings (facility_id, requester_id, start_time, end_time, purpose, attendees, status, last_actor_id)
SELECT f.id, u.id, '2026-11-24T09:00:00+00:00', '2026-11-24T11:00:00+00:00', 'Department seminar', 25, 'CONFIRMED', u.id
FROM facilities f, users u WHERE f.code = 'SEM-201' AND u.username = 'faculty1';

INSERT INTO bookings (facility_id, requester_id, start_time, end_time, purpose, attendees, status, last_actor_id)
SELECT f.id, u.id, '2026-11-25T10:00:00+00:00', '2026-11-25T12:00:00+00:00', 'Practical session preparation', 30, 'REQUESTED', NULL
FROM facilities f, users u WHERE f.code = 'LAB-101' AND u.username = 'faculty1';

INSERT INTO tickets (facility_id, reporter_id, source, title, description, category, priority, status, assignee_id, triage_rules, sla_due_at)
SELECT f.id, u.id, 'USER', 'Water leak under sink in Library Study Room 2', 'Water pooling under the basin cabinet.', 'PLUMBING', 'HIGH', 'ASSIGNED',
       (SELECT id FROM users WHERE username = 'tech1'),
       '["seed data: manually classified (category=PLUMBING, priority=HIGH)"]', '2026-11-20T09:00:00+00:00'
FROM facilities f, users u WHERE f.code = 'LIB-RM2' AND u.username = 'faculty1';

INSERT INTO tickets (facility_id, reporter_id, source, title, description, category, priority, status, triage_rules, sla_due_at)
SELECT f.id, u.id, 'USER', 'Air conditioning not cooling in Seminar Room 201', 'Room is warm during afternoon sessions.', 'HVAC', 'MEDIUM', 'INTAKE',
       '["seed data: manually classified (category=HVAC, priority=MEDIUM)"]', '2026-11-22T09:00:00+00:00'
FROM facilities f, users u WHERE f.code = 'SEM-201' AND u.username = 'student1';

INSERT INTO tickets (facility_id, reporter_id, source, title, description, category, priority, status, assignee_id, triage_rules, sla_due_at)
SELECT f.id, u.id, 'SENSOR', 'Sensor alert: SMOKE_LEVEL 0.82 at CHEM-LAB', 'Generated from sensor event GW-SEED-0001.', 'SAFETY', 'CRITICAL', 'INSPECTION',
       (SELECT id FROM users WHERE username = 'tech2'),
       '["threshold rule: SMOKE_LEVEL reading 0.82 > 0.5"]', '2026-11-19T15:00:00+00:00'
FROM facilities f, users u WHERE f.code = 'CHEM-LAB' AND u.username = 'sensor-gw';

INSERT INTO sensor_events (event_key, facility_id, sensor_type, reading, breached, ticket_id)
SELECT 'GW-SEED-0001', f.id, 'SMOKE_LEVEL', 0.82, TRUE, t.id
FROM facilities f, tickets t WHERE f.code = 'CHEM-LAB' AND t.title = 'Sensor alert: SMOKE_LEVEL 0.82 at CHEM-LAB';
