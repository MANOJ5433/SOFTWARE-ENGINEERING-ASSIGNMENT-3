# Smart Campus Facility and Maintenance Platform

A containerised full-stack application for campus facility booking and maintenance ticket management.

- **Frontend:** HTML, CSS and vanilla JavaScript (served by Nginx)
- **Backend:** Python 3.12, Flask REST API, served by Gunicorn (two identical containers)
- **Database:** PostgreSQL 16 with a database-level exclusion constraint against overlapping bookings
- **Load balancer / reverse proxy:** Nginx (round-robin across `backend1` and `backend2`)
- **Containers:** Docker and Docker Compose
- **Version control:** Git and GitHub

No paid services, no external AI API, and no external network calls are required.

---

## 1. Prerequisites (Windows)

| Requirement | How to check |
|---|---|
| Windows 10 (22H2) or Windows 11 | `winver` |
| WSL 2 | `wsl --status` (install with `wsl --install` from an administrator PowerShell, then restart) |
| Docker Desktop, WSL 2 backend enabled | Docker Desktop > Settings > General > "Use the WSL 2 based engine" |
| Docker Compose v2 | `docker compose version` |
| Git for Windows | `git --version` |
| Python 3.10+ (only for the test scripts, standard library only) | `python --version` |

## 2. Quick start

Open **PowerShell** (not as administrator) in the folder where you want the project:

```powershell
git clone https://github.com/<your-github-user>/smart-campus-platform.git
cd smart-campus-platform

Copy-Item .env.example .env
notepad .env          # change POSTGRES_PASSWORD to any value you like, then save

docker compose up -d --build
docker compose ps     # db, backend1, backend2 and nginx should show "running" (db and backends "healthy")
```

Open **http://localhost:8080** in a browser.

First run takes a few minutes while images download. On later runs `docker compose up -d` is enough.

To stop the stack without losing data: `docker compose down`
To delete everything, including the database volume, and rebuild from scratch: `docker compose down -v`

## 3. Demo accounts

The demonstration accounts below are seeded by `db/init/02_seed.sql`. They are for local evaluation only. The database stores only SHA-256 hashes of these tokens, not the tokens themselves.

| Username | Role | Token (paste into "Bearer token") |
|---|---|---|
| admin | Campus administrator | `tok-admin-demo` |
| facmgr | Facility manager | `tok-facmgr-demo` |
| approver | Department approver | `tok-approver-demo` |
| tech1 | Maintenance technician | `tok-tech1-demo` |
| tech2 | Maintenance technician | `tok-tech2-demo` |
| faculty1 | Faculty member | `tok-faculty-demo` |
| student1 | Student | `tok-student-demo` |
| sensor-gw | Sensor gateway (machine account) | `tok-sensor-demo` |

The browser shows the buttons that each ticket or booking state allows. The backend decides who may press them, and a refused action displays the server's error message.

## 4. Demonstration walkthrough

**Journey A: booking with approval.**
1. Sign in as `faculty1`, open *Book facility*, choose **LAB-101** (restricted), enter a future time and purpose, submit. The booking is `REQUESTED`.
2. Sign in as `approver` (or `facmgr`), open *Bookings*, press **approve**. Status becomes `APPROVED`.
3. Sign in as `faculty1` and press **confirm**, then **start** and **complete** once the slot begins.
4. Try the same slot again as `faculty1`: the API rejects it with `BOOKING_OVERLAP`.

**Journey B: sensor alert to closed ticket, with a linked DevOps step.**
1. Send a smoke reading from the gateway (PowerShell):
   ```powershell
   $h = @{ Authorization = "Bearer tok-sensor-demo"; "Idempotency-Key" = "demo-sensor-0001" }
   $b = '{"event_key":"GW-DEMO-0001","facility_id":5,"sensor_type":"SMOKE_LEVEL","reading":0.9}'
   Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/sensor-events -Headers $h -ContentType "application/json" -Body $b
   ```
   (`facility_id` 5 is CHEM-LAB in the seed data.) A `CRITICAL` safety ticket is created.
2. As `facmgr`, open *Tickets*, select the ticket, assign it to `tech2`.
3. As `tech2`, start inspection (add notes), then resolve (add resolution notes).
4. As `facmgr`, press **Close (authorise)**. Closure is refused if no inspection notes exist.
5. As `facmgr`, press **Link DevOps issue**. The record shows `SYNCED`. To demonstrate retry, see section 7.

## 5. Running the automated checks

All test scripts use only the Python standard library and the demo tokens above.

```powershell
cd smart-campus-platform
$env:BASE_URL = "http://localhost:8080"
python scripts\test_api.py                       # functional, validation, RBAC, overlap, idempotency checks
python scripts\concurrency_test.py --threads 20  # simultaneous requests and their invariants
python scripts\load_test.py --threads 20 --seconds 20   # bounded load experiment (reports measured numbers)
```

Or run the first two together from `scripts\run_all_checks.ps1`. Every script exits with code 0 only if all of its checks pass. Results are printed, not pre-recorded.

## 6. Two backend instances and load balancing

Every API response carries an `X-Served-By` header that names the backend container that handled it. Repeat a request several times to see Nginx alternate between `backend-1` and `backend-2`:

```powershell
1..6 | ForEach-Object { (Invoke-WebRequest http://localhost:8080/api/health -UseBasicParsing).Headers["X-Served-By"] }
```

## 7. Restart and persistence tests

```powershell
.\scripts\restart_test.ps1
```

The script takes a snapshot of bookings, tickets and the audit trail, restarts one backend, then the other, then the database container, and verifies that every record is still present and unchanged. Failure to match causes a non-zero exit code.

To test a *simulated external outage*:
1. Set `SIMULATE_TRACKER_OUTAGE=true` in `.env`, then run `docker compose up -d` (this recreates the backend containers with the new value).
2. Create a DevOps link from a ticket. It is stored as `PENDING` with a recorded error.
3. Set `SIMULATE_TRACKER_OUTAGE=false`, run `docker compose up -d`, then press **Retry** on the link. It becomes `SYNCED`.

## 8. Repository layout

```
smart-campus-platform/
├── backend/                 Flask API
│   ├── app/                 application package (routes, state machines, triage, idempotency, DB layer)
│   ├── wsgi.py              gunicorn entry point
│   ├── requirements.txt     pinned Python dependencies
│   └── Dockerfile           backend image (used by backend1 and backend2)
├── db/init/                 PostgreSQL schema and seed data (run automatically on first start)
├── frontend/                static HTML, CSS and JavaScript
├── nginx/default.conf       reverse proxy and load balancer configuration
├── scripts/                 automated tests, load experiment, persistence checks, Windows runners
├── docs/                    API contract, state models and Git workflow commands
├── docker-compose.yml       service definitions, networks, volumes and health checks
├── .env.example             template for local configuration (copy to .env)
├── .gitignore               keeps secrets, databases and caches out of Git
└── README.md
```

## 9. API

See [docs/API.md](docs/API.md) for every endpoint, request and response shape, error code, role rule and state model.

## 10. Local development without Docker (optional)

```powershell
cd backend
python -m pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///campus-local.db"   # SQLite is for local development only
python -m app.cli init-db --url $env:DATABASE_URL --dir ..\db\init
$env:PORT = "5000"
python -m app
```

Then `BASE_URL=http://127.0.0.1:5000` for the test scripts. The SQLite path does not provide the PostgreSQL row locks or exclusion constraint, so the Docker stack is the reference environment for the assignment evidence.

## 11. Known limitations

- Authentication uses static bearer tokens for demonstration. Production would need managed identities, token expiry and rotation.
- The "external" issue tracker is simulated inside the backend (`LOCAL_SIMULATED` mode). No real DevOps service is contacted.
- Triage uses deterministic keyword rules and fixed thresholds. No trained model is involved.
- Sensor intake accepts readings from an authenticated gateway account; there is no device-level signing.
- Load testing is bounded to the number of clients you choose on your machine. The project makes no claim of supporting any particular number of simultaneous users.
