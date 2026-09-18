# KHATTAH

KHATTAH is a mobile-first circle-based financial participation platform foundation.

## Run

- `pnpm --filter @workspace/khattah run dev` — run the Flask application
- `python3 -m compileall -q artifacts/khattah` — check Python syntax

## Stack

- Frontend: semantic HTML5, CSS, and vanilla JavaScript
- Backend: Python Flask
- Database: SQLite

## Structure

- `artifacts/khattah/app.py` — Flask setup, web routes, API-ready JSON routes, and SQLite initialization
- `artifacts/khattah/services/khattah.py` — Khattah application service layer
- `artifacts/khattah/templates/` — server-rendered HTML pages
- `artifacts/khattah/static/` — CSS and vanilla JavaScript
- `artifacts/khattah/instance/khattah.sqlite3` — local runtime database, not committed

## Architecture decisions

- Khattah status interpretation and future business rules belong in the Python service layer, never templates or browser JavaScript.
- JSON endpoints use the `/api/v1/` namespace so a future mobile client can consume the same service layer.
- Unknown financial, circle qualification, payment, and reward rules are shown as not configured rather than inferred.
- Passwords are stored as secure hashes; the session signing key comes from `SESSION_SECRET`.

## Product

The current foundation includes a landing page, account registration and login, dashboard, circle, invitations, transactions, profile, and settings. Payment processing and reward payout logic are intentionally absent.

## User preferences

- Do not use React, Next.js, Vue, TypeScript, or another frontend framework.
- Keep the architecture simple, clean, and mobile-first.
- Do not invent Khattah business rules.