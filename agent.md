# Agent Guide

This project is a Flask application that tracks employee attendance, provides an admin panel for schedules, and includes a PDF analysis tool with optional AI validation. Use this guide as a quick reference when making changes.

## Project Snapshot
- Main entry point: `app.py`
- Templates: `templates/`
- Static assets: `static/`
- Admin panel modules: `admin_panel/`
- ORM models and DB setup: `models.py` (SQLite dev database `fichaje.db`)

## Local Setup
- Python version: 3.11+ recommended
- Create/activate virtualenv if needed (`python -m venv .venv`)
- Install dependencies: `pip install -r requirements.txt`
- Optional AI features:
  - Install `openai` (already in requirements)
  - Set `OPENAI_API_KEY` and (optionally) `PDF_AI_MODEL`
- Run the app: `flask --app app.py run` (uses `Europe/Madrid` timezone when available)

## Coding Patterns
- Database access: wrap queries in `SessionLocal()` context and ensure `db.close()` in `finally`.
- Time handling: use helpers (`to_local`, `ensure_aware_utc`, `local_day_bounds_utc`) to avoid naive datetimes.
- RBAC: decorate routes with `@login_required` plus helper guards (`admin_required`, `require_view_user`, etc.).
- Forms use WTForms via `Flask-WTF`; remember CSRF tokens.

## Frontend Notes
- Templates are Jinja2; reuse shared components in `base.html`.
- Use the design tokens already present (buttons, cards, dark mode support).
- For the PDF tool, visuals live in `templates/pdf_tool.html` and rely on client-side pdf.js rendering.

## Testing & QA
- Run unit tests with `pytest`.
- For major changes, manually hit key routes:
  - `/login`, `/dashboard` (if present), `/pdf`, admin schedule pages.
- When editing SQL queries, validate with a populated `fichaje.db` (demo data loads automatically on app start).

## Fast Commands
- `pip install -r requirements.txt`
- `flask --app app.py run`
- `pytest`
