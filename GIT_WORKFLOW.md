# Git and GitHub workflow

Run these commands yourself, in PowerShell, from the project folder. They create the real commit history
in your repository. Replace the values in angle brackets. Nothing in this project pre-creates commits,
branches, tags or a remote.

The sequence builds the project in stages. Each stage is a feature branch that is committed and merged.
At the end there is one deliberate merge conflict, which you resolve yourself.

## 1. Initialise and commit the scaffolding on main

```powershell
git init -b main
git config user.name "M. Sai Teja"
git config user.email "<your-email@example.com>"
git add .gitignore .gitattributes .env.example README.md docs/
git status                       # .env must NOT appear; it is git-ignored
git commit -m "chore: repository scaffolding, ignore rules and documentation"
```

## 2. Feature branch: database schema and seed data

```powershell
git switch -c feature/database-schema
git add db/init/
git commit -m "feat(db): add PostgreSQL schema with booking exclusion constraint and seed data"
git switch main
git merge --no-ff feature/database-schema -m "merge: database schema and seed data"
```

## 3. Feature branch: backend core (configuration, DB layer, auth, idempotency)

```powershell
git switch -c feature/backend-core
git add backend/app/__init__.py backend/app/blueprint.py backend/app/config.py backend/app/constants.py `
        backend/app/db.py backend/app/errors.py backend/app/util.py backend/app/auth.py backend/app/audit.py `
        backend/app/idempotency.py backend/app/serializers.py backend/app/__main__.py backend/app/cli.py `
        backend/wsgi.py backend/requirements.txt backend/Dockerfile backend/.dockerignore
git commit -m "feat(backend): core app factory, PostgreSQL access layer, token auth and idempotency"
git switch main
git merge --no-ff feature/backend-core -m "merge: backend core"
```

## 4. Feature branch: booking API

```powershell
git switch -c feature/booking-api
git add backend/app/routes_bookings.py
git commit -m "feat(api): booking creation with row locking, overlap rejection and approval state machine"
git switch main
git merge --no-ff feature/booking-api -m "merge: booking API"
```

## 5. Feature branch: ticket triage and lifecycle

```powershell
git switch -c feature/ticket-triage
git add backend/app/triage.py backend/app/routes_tickets.py backend/app/routes_core.py
git commit -m "feat(tickets): deterministic triage, SLA, optimistic versioning and sensor intake"
```

## 6. Deliberate merge conflict: two edits to the same README line

While `feature/ticket-triage` is open, change the same heading on main and on the feature branch.

```powershell
# (a) change on main
git switch main
# Open README.md in an editor, change the heading "## 3. Demo accounts" to "## 3. Demo accounts (local evaluation only)", save.
git commit -am "docs: state the scope of demo accounts"

# (b) conflicting change on the feature branch
git switch feature/ticket-triage
# Open README.md, change the same heading to "## 3. Demo accounts for demonstration", save.
git commit -am "docs: reword demo account heading"

# (c) merge and resolve
git switch main
git merge feature/ticket-triage        # Git reports: CONFLICT (content): Merge conflict in README.md
git status                             # shows: both modified: README.md
notepad README.md                      # delete the <<<<<<< / ======= / >>>>>>> markers and keep one heading
git add README.md
git commit -m "merge: ticket triage; resolve README heading conflict"
```

Keep the output of `git status` and `git diff --name-only --diff-filter=U` before you resolve the conflict.
These are the conflict evidence for Q4.

## 7. Feature branch: frontend

```powershell
git switch -c feature/frontend
git add frontend/
git commit -m "feat(ui): dashboard, facility calendar, booking form, approvals and ticket screens"
git switch main
git merge --no-ff feature/frontend -m "merge: frontend screens"
```

## 8. Feature branch: deployment (Docker, Compose, Nginx, checks)

```powershell
git switch -c feature/deployment
git add docker-compose.yml nginx/ scripts/
git commit -m "feat(deploy): Docker Compose stack with two backends, Nginx load balancer and test scripts"
git switch main
git merge --no-ff feature/deployment -m "merge: containerised deployment and checks"
```

## 9. Push to GitHub and record a review

Create an empty repository on GitHub named `smart-campus-platform` (do not add a README or .gitignore there).

```powershell
git remote add origin https://github.com/<your-github-user>/smart-campus-platform.git
git push -u origin main
```

To record a reviewed change, create one more branch with a small real change, open a pull request on GitHub
from that branch into `main`, read through the diff, and merge it there. Because this is an individual
assignment, write in the pull request description that the review is a self-review. Do not present it as
review by another person.

```powershell
git switch -c feature/readme-quickstart-check
# make a real improvement, e.g. correct a command in README.md
git commit -am "docs: correct quick start command"
git push -u origin feature/readme-quickstart-check
# open the pull request on GitHub, review the diff, merge it, then:
git switch main
git pull
```

## 10. Stable release identifier

```powershell
git tag -a v1.0.0 -m "Release 1.0.0: booking, tickets, sensor intake, containerised deployment"
git push origin v1.0.0
```

## 11. Evidence commands for the report

```powershell
git log --oneline --graph --decorate --all
git branch -a
git tag --list
git show-ref --tags
git ls-files | Select-String -Pattern "^\.env$"     # must print nothing
```
