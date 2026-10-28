# SwasthyaGrid REST API Backend

This package exposes a FastAPI REST backend for a React/mobile client or a separately deployed frontend. It includes authentication, role-based authorization, complaint creation and routing, evidence uploads, case status changes, admin user management, audit events, report exports, optional AI-assisted triage, SQLAlchemy, SQLite for local tests, and PostgreSQL support.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # Windows; on macOS/Linux use: cp .env.example .env
uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs`; health check: `/api/health`.

## Production configuration

Set environment variables or your host's secret manager values:

- `APP_ENV=production`
- `ALLOW_DEMO_LOGIN=false`
- `DATABASE_URL=postgresql+psycopg://...` (use managed PostgreSQL)
- `BOOTSTRAP_ADMIN_PASSWORD` (initial password, minimum 10 characters)
- `TOKEN_SECRET` (long, random, unique secret)
- `CORS_ORIGINS` (comma-separated frontend origin allowlist; do not use `*` for a credentialed/private app)
- optionally `GROQ_API_KEY` and/or `GEMINI_API_KEY`

Never deploy with demo credentials or the example token secret. When the database is empty, the initial Admin account is created from `BOOTSTRAP_ADMIN_PASSWORD`. Afterward, the Admin can create the other roles. The UI package has a separate `README.md` with Streamlit Community Cloud deployment instructions.

## Authentication

Call `POST /api/auth/login` with username/password. Use returned `access_token` as `Authorization: Bearer <token>`. Tokens expire after eight hours. HTTPS is required for public deployment. Share the same `DATABASE_URL` and `TOKEN_SECRET` with any services that must share data and accept the same signed token.
