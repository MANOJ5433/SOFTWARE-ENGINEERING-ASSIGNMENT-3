# API contract

Base path: `/api` (through Nginx on `http://localhost:8080`).

## Conventions

- **Authentication:** `Authorization: Bearer <token>` on every endpoint except `GET /api/health`.
- **Idempotency:** every `POST` that creates or changes a record requires `Idempotency-Key: <8-128 chars>`.
  - A retry with the same key and the same body returns the original response with `Idempotent-Replayed: true`.
  - The same key with a different body returns `422 IDEMPOTENCY_KEY_REUSED`.
  - A missing key returns `400 IDEMPOTENCY_KEY_REQUIRED`.
- **Optimistic concurrency:** every booking or ticket change sends the `version` it last read. If the record has changed, the server returns `409 VERSION_CONFLICT` and writes nothing.
- **Timestamps:** ISO-8601 in UTC. Inputs with an offset or a `Z` suffix are accepted.
- **Errors:** `{"error": {"code": "...", "message": "...", "details": {...}}}`.
- **Instance header:** every response includes `X-Served-By: backend-1|backend-2`.

## Error codes

| HTTP | Code | Meaning |
|---|---|---|
| 400 | BAD_JSON | Body is not a JSON object |
| 400 | IDEMPOTENCY_KEY_REQUIRED | Create or change request sent without `Idempotency-Key` |
| 401 | UNAUTHENTICATED | Missing, unknown or disabled token |
| 403 | FORBIDDEN | Role may not perform this action |
| 403 | ROLE_RESTRICTED | Student attempted to book a restricted facility |
| 404 | NOT_FOUND / FACILITY_NOT_FOUND | Resource does not exist or is inactive |
| 409 | BOOKING_OVERLAP | Facility already reserved for an overlapping interval |
| 409 | VERSION_CONFLICT | Record changed since it was read |
| 409 | INVALID_TRANSITION | Action not allowed from the current state |
| 409 | INSPECTION_REQUIRED | Attempt to close a ticket without inspection notes |
| 409 | IDEMPOTENT_REQUEST_IN_PROGRESS | Same key is still being processed; retry shortly |
| 409 | CONFLICT | Other uniqueness conflict |
| 422 | VALIDATION_ERROR | Field missing, wrong type, out of range or inconsistent |
| 422 | CAPACITY_EXCEEDED | Attendees above facility capacity |
| 422 | IDEMPOTENCY_KEY_REUSED | Key reused with a different request body |
| 500 | INTERNAL_ERROR | Unexpected failure; the change was rolled back |

## Endpoints

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | /health | public | Database check; returns instance name |
| GET | /me | any authenticated | Identity and role |
| GET | /facilities | any | Active facilities |
| POST | /facilities | admin, facility_manager | Create facility |
| PATCH | /facilities/{id} | admin, facility_manager | Update name, location, capacity, restricted, active |
| GET | /facilities/{id}/calendar?date=YYYY-MM-DD | any | Non-cancelled bookings on that UTC day |
| GET | /bookings?status= | any (students and faculty see own only) | List bookings |
| GET | /bookings/{id} | requester or staff | One booking |
| POST | /bookings | any except sensor | **Idempotent.** Body: facility_id, start_time, end_time, purpose, attendees |
| POST | /bookings/{id}/transition | see table below | **Idempotent.** Body: action, version, note? |
| GET | /tickets?status=&priority= | staff see all; technicians see assigned; others see own | List tickets, ordered by priority |
| GET | /tickets/{id} | staff, assignee or reporter | One ticket with triage rules and SLA |
| POST | /tickets | any except sensor | **Idempotent.** Body: title, description?, facility_id?, category?, priority? (managers only) |
| PATCH | /tickets/{id} | admin, facility_manager | Change priority. Body: priority, version |
| POST | /tickets/{id}/transition | see table below | **Idempotent.** Body: action, version, notes?, assignee_id? |
| POST | /sensor-events | sensor, facility_manager, admin | **Idempotent and deduplicated** by event_key. Body: event_key, facility_id, sensor_type, reading |
| GET | /tickets/{id}/links | staff, assignee or reporter | Linked integration records |
| GET | /tickets/{id}/links | staff, assignee or reporter | Linked integration records for a ticket |
| POST | /tickets/{id}/links | admin, facility_manager, technician, approver | **Idempotent.** Body: provider = `devops-issue`, title |
| POST | /integrations/{id}/retry | staff | **Idempotent.** Retries a PENDING link |
| GET | /users?role= | admin, facility_manager | Active users (for assignment) |
| GET | /dashboard | any | Counts by status, open priorities, SLA breaches |
| GET | /audit?entity_type=&entity_id= | admin, facility_manager, approver | Latest 200 audit events |

## Booking state model

States: `REQUESTED`, `APPROVED`, `CONFIRMED`, `IN_USE`, `COMPLETED`, `CANCELLED`.

| From | Action | To | Allowed roles |
|---|---|---|---|
| REQUESTED | approve | APPROVED | approver, facility_manager, admin |
| REQUESTED | reject | CANCELLED | approver, facility_manager, admin |
| REQUESTED | cancel | CANCELLED | manager roles or requester |
| APPROVED | confirm | CONFIRMED | manager roles or requester |
| APPROVED | cancel | CANCELLED | manager roles or requester |
| CONFIRMED | start | IN_USE | manager roles or requester |
| CONFIRMED | cancel | CANCELLED | manager roles or requester |
| IN_USE | complete | COMPLETED | manager roles or requester |

Unrestricted facilities are created directly as `CONFIRMED`. Restricted facilities are created as `REQUESTED`. A booking is *active* (and blocks the slot) while it is `REQUESTED`, `APPROVED`, `CONFIRMED` or `IN_USE`.

## Ticket state model

States: `INTAKE`, `ASSIGNED`, `INSPECTION`, `PENDING_WORK`, `RESOLVED`, `CLOSED`.

| From | Action | To | Allowed roles |
|---|---|---|---|
| INTAKE | assign | ASSIGNED | admin, facility_manager |
| ASSIGNED | assign (reassign) | ASSIGNED | admin, facility_manager |
| ASSIGNED | start_inspection | INSPECTION | assigned technician or manager |
| INSPECTION | pending_work | PENDING_WORK | assigned technician or manager; notes required |
| INSPECTION | resolve | RESOLVED | assigned technician or manager; notes required |
| PENDING_WORK | resolve | RESOLVED | assigned technician or manager; notes required |
| RESOLVED | close | CLOSED | admin, facility_manager; inspection notes must exist |
| RESOLVED | reopen | ASSIGNED | admin, facility_manager |

SLA deadlines follow priority: CRITICAL 4 hours, HIGH 24 hours, MEDIUM 72 hours, LOW 168 hours from creation.

## Triage rules (deterministic)

- Category: first matching keyword group in this order: SAFETY, ELECTRICAL, PLUMBING, HVAC, FURNITURE_FIXTURE. Otherwise OTHER.
- Priority: CRITICAL keywords (smoke, fire, gas, burning, sparks, flood), then HIGH (leak, outage, unsafe, broken, overheating, lock), then LOW (cosmetic, paint, squeak, minor, scratch). Otherwise MEDIUM.
- Every response includes `triage_rules`, which lists the keyword that fired.
- Sensor readings: SMOKE_LEVEL above the threshold creates a CRITICAL SAFETY ticket. TEMPERATURE above the threshold creates an HVAC ticket, HIGH when at least 5 degrees above, otherwise MEDIUM.
