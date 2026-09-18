# KHATTAH

KHATTAH is a mobile-first package-based financial participation platform foundation.

## Run

- `pnpm --filter @workspace/khattah run dev` — run the Flask application
- `python3 -m compileall -q artifacts/khattah` — check Python syntax
- `pnpm --filter @workspace/khattah run test` — run the Phase 2 backend regression suite

## Stack

- Frontend: semantic HTML5, CSS, and vanilla JavaScript
- Backend: Python Flask
- Database: SQLite

## Structure

- `artifacts/khattah/app.py` — Flask setup, web routes, API-ready JSON routes, and SQLite initialization
- `artifacts/khattah/services/khattah.py` — Khattah application service layer
- `artifacts/khattah/services/phone_verification.py` — backend OTP lifecycle and replaceable mock SMS adapter
- `artifacts/khattah/services/i18n.py` — shared English/Arabic catalog and locale normalization
- `artifacts/khattah/templates/` — server-rendered HTML pages
- `artifacts/khattah/static/` — CSS and vanilla JavaScript
- `artifacts/khattah/instance/khattah.sqlite3` — local runtime database, not committed

## Architecture decisions

- Khattah status interpretation and future business rules belong in the Python service layer, never templates or browser JavaScript.
- JSON endpoints use the `/api/v1/` namespace so a future mobile client can consume the same service layer.
- A package is event-driven and completes when its first five paid/activated participants qualify; there is no monthly completion or reward restriction.
- Completed packages, qualifying participants, activations, rewards, transactions, and audit events remain in permanent history.
- Canonical web/API terminology is Package (`/packages`, `/api/v1/package(s)`); legacy Circle routes/API aliases remain for compatibility.
- SQLite persistence retains historical `circles`, `circle_participants`, and `circle_id` names as compatibility identifiers; no duplicate package tables are created.
- Payment amounts, payout formulas, fees, reward amounts, and real-money processing remain disabled and unconfigured.
- Passwords are stored as secure hashes; the session signing key comes from `SESSION_SECRET`.
- Admin routes require an administrator account, and unsafe session-backed requests require a CSRF token.
- Registration requires a unique normalized mobile number verified by a short-lived, hashed OTP with attempt and resend limits.
- The current SMS adapter is development-only and keeps mock codes transient and server-side; codes are never exposed through HTML, APIs, logs, or admin pages.
- Demo mode generates the fixed mock OTP `123456`; production mode always generates random OTPs and never accepts the demo code as a bypass.
- Development-only member/admin accounts use the reserved `khattah.test` domain, are seeded only in demo mode, and are rejected when demo mode is disabled.
- English and Arabic use one shared catalog, persisted language preferences, and a directional HTML/CSS layout; phone numbers and OTPs remain LTR inside Arabic.

## Product

Phase 2 includes phone-verified registration and login, invitations, five-position package progress, multiple-package history, admin-only mock activations, reward eligibility records, transactions, audit history, profile, settings, and `/api/v1/` JSON endpoints. Real SMS delivery, payment processing, and reward payouts are intentionally absent.

## User preferences

- Do not use React, Next.js, Vue, TypeScript, or another frontend framework.
- Keep the architecture simple, clean, and mobile-first.
- Do not invent Khattah business rules.