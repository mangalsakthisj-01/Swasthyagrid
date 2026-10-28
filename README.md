# SwasthyaGrid — Civic Intelligence & Health-Risk Triage

**A deployable full-stack starter project** with a Streamlit frontend, a shared Python service/database backend, and an optional FastAPI REST API. The project supports four roles: Citizen, Field Officer, Admin, and Representative.

> **Important:** This is a prototype starter, not a certified emergency dispatch, medical triage, or production government system. AI output is advisory; high-priority safety rules bypass normal queues but still require human follow-up. Do not use demo accounts or local SQLite for real public data.

## Included in this ZIP

- `app.py` — responsive Streamlit frontend with four role dashboards, charts, report forms, case tracking, and evidence views.
- `backend/services.py` — shared business logic for users, complaint creation, routing, updates, evidence, analytics, and audit history.
- `backend/models.py`, `backend/database.py` — SQLAlchemy data layer. Uses SQLite locally; supports PostgreSQL via `DATABASE_URL`.
- `backend/security.py` — PBKDF2 password hashing and HMAC-signed, expiring API tokens.
- `backend/triage.py` — critical-safety override, explainable rule-based triage, optional Gemini/Groq assessment. Without an AI key, the app uses the rules fallback.
- `backend/api.py` — optional REST API for another web frontend/mobile app; interactive OpenAPI docs at `/docs`.
- `requirements.txt`, `.streamlit/config.toml`, `.env.example`, `start.bat`, `start.sh` — local run/deployment support.
- `Dockerfile.streamlit`, `Dockerfile.api` — separate Docker start targets for frontend service and REST API service.

## Quick start on Windows

1. Extract the ZIP to a regular folder.
2. Install Python 3.11 from [python.org](https://www.python.org/downloads/) if it is not installed. During installation on Windows, enable **Add Python to PATH**.
3. Double-click `start.bat`. It creates a virtual environment, installs dependencies, and starts the frontend. The first install needs internet access.
4. Open `http://localhost:8501` in Chrome or Edge.
5. A local demo database is created under `data/swasthyagrid.db`.

If Windows cannot find `py`, open a terminal in the extracted folder and run:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

The first local demo login credentials are intentionally public sample credentials:

| Role | User ID | Password |
|---|---|---|
| Admin | `admin` | `Admin@12345` |
| Field Officer | `officer` | `Officer@12345` |
| Representative | `representative` | `Rep@123456` |
| Citizen | `citizen` | `Citizen@12345` |

**Local demo credentials are not secure. Do not expose a deployment using these credentials to the public.** Local demo mode inserts fictional sample reports labelled as demo data.

## Deploy the full app on Streamlit Community Cloud

Streamlit Community Cloud deploys from a GitHub repository and asks you to select the repository, branch, and entrypoint file. The entrypoint for this project is `app.py`. Official guides: [Deploy an app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy) and [application dependencies](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

1. Extract the ZIP on your computer.
2. Create a GitHub repository. Upload the **contents** of the extracted folder (so `app.py` and `requirements.txt` are at the repository root). Do not upload your local `.env`, database, virtual environment, or API keys.
3. Go to [share.streamlit.io](https://share.streamlit.io/) and sign in with GitHub.
4. Select **Create app**, choose the repository and branch, set **Main file path** to `app.py`, then deploy.
5. Before using real accounts or real reports, open app settings → **Secrets** and configure production secrets similar to this TOML example:

```toml
APP_ENV = "production"
ALLOW_DEMO_LOGIN = false
DATABASE_URL = "postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=require"
BOOTSTRAP_ADMIN_PASSWORD = "REPLACE_WITH_A_LONG_UNIQUE_PASSWORD"
TOKEN_SECRET = "REPLACE_WITH_A_LONG_RANDOM_SECRET"
MAX_UPLOAD_MB = "10"
CORS_ORIGINS = "https://YOUR-FRONTEND-DOMAIN,http://localhost:5173"
# Optional: enable one provider (the citizen must explicitly consent to external AI processing)
GROQ_API_KEY = ""
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GEMINI_API_KEY = ""
GEMINI_MODEL = "gemini-2.5-flash"
```

Replace the database placeholders with a real PostgreSQL database connection string from your database host. Keep the database password private. Never commit the values above to GitHub. Streamlit's official secret guidance: https://docs.streamlit.io/deploy/concepts/secrets

**Persistent database is required for real use.** The local SQLite file is useful for local testing but is not a suitable durable database for a cloud demo that may restart or redeploy. Provision PostgreSQL (for example via a managed database provider) and set `DATABASE_URL`. Uploaded files are stored as database binary records; use managed Postgres and backups for persistence.

If `ALLOW_DEMO_LOGIN=false` and the database is empty, the app seeds only an initial `admin` account from `BOOTSTRAP_ADMIN_PASSWORD`. Use the same minimum 10-character policy. After the first login, create accounts for officers, representatives, and citizens from **User & role management**. Do not leave the bootstrap password in a shared message or source file.

## Configure Groq or Gemini for optional AI-assisted review

The app does not require an AI API key to run. Its rules engine always works as a fallback and never automatically rejects a case merely because an attachment is missing or uncertain.

- To configure Groq, set `GROQ_API_KEY` in your deployment secrets.
- To configure Gemini, set `GEMINI_API_KEY`.
- The citizen submission form asks for explicit consent before sending report text and an image to a configured external AI provider. If consent is not provided (or no key is configured), rule-based triage runs locally.
- Video and audio attachments are stored as evidence but are not sent to the vision model by this version.
- An AI result is a relevance/urgency recommendation, not proof of truth, a disease diagnosis, or an official outbreak declaration.

## Optional separate REST API backend

The Streamlit app already uses `backend/services.py` as its backend; you do **not** have to run FastAPI separately for Streamlit to work. If you need REST endpoints for a React frontend, mobile app, or external integration, run the included API as a second service:

```bash
pip install -r requirements.txt
uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000/docs` for interactive API documentation. Health endpoint: `GET /api/health`.

REST endpoints include:

- `POST /api/auth/login`, `GET /api/me`
- `GET/POST /api/complaints`
- `GET /api/complaints/{id}`, `PATCH /api/complaints/{id}/status`
- `POST /api/complaints/{id}/assignment`
- `POST /api/complaints/{id}/evidence`, `GET /api/complaints/{id}/evidence`
- `GET /api/reports/summary`, `GET /api/reports/export.csv`
- `GET/POST/PATCH /api/users` and `GET /api/audit`

If you deploy the API separately on a host such as Render or Railway, set the **same** `DATABASE_URL`, `TOKEN_SECRET`, `ALLOW_DEMO_LOGIN=false`, and appropriate production settings on both services. Do not deploy the API with the default local token secret. Use HTTPS at the host/proxy. For the REST API container, use `Dockerfile.api`; for the Streamlit web service, use `Dockerfile.streamlit`.

## Important application behavior

- **Critical-safety bypass:** configured phrases (for example, reports of a road collapse or live electrical wire) or user-reported Critical severity route the case to `Escalated` immediately. If available, the app assigns an officer and representative. This is a precautionary workflow trigger, not confirmation that the event is real.
- **AI-assisted review:** the label and confidence indicate an advisory assessment. Mismatches or uncertain media are sent for human review rather than silently discarded.
- **Roles:** Citizen can create and track their own reports and reopen a resolved report; Field Officer can update cases in their jurisdiction; Admin can create/manage users, assign cases, change status, inspect audit history and export reports; Representative gets jurisdiction-based oversight and exports without citizen names.
- **Evidence:** attachments are stored in the database. Configure `MAX_UPLOAD_MB` to set a limit. Database backups also need to cover uploaded evidence.
- **Audit trail:** key account, complaint, assignment, evidence, and status changes create audit records. The application writes audit entries; administrators should still back up and restrict database access.
- **Hotspots:** visible clusters require at least three complaints in the same area/category. These are signals for investigation, not proof of a health event. Confirm with authorised public-health officials before publishing alerts.

## Testing and troubleshooting

- Python compile check: `python -m compileall app.py backend`
- Local REST health check after starting API: `http://localhost:8000/api/health`
- If the Streamlit page shows a module error, run `pip install -r requirements.txt` from the project root.
- If login fails, check username/password and that the database URL points to the intended database.
- If a production deployment shows no account, set `BOOTSTRAP_ADMIN_PASSWORD` in the host's secrets, set `ALLOW_DEMO_LOGIN=false`, and restart with an empty/appropriate database.
- If API authentication fails across restarts or services, set a stable `TOKEN_SECRET` secret shared by both API instances.

## Production readiness checklist

Before handling genuine civic or health-related information: use a managed database with backups; use unique admin passwords and a long random token secret; disable demo mode; restrict database and API access; configure HTTPS; test authorization boundaries; set data retention and deletion rules; disclose any external AI processing; monitor error logs; and obtain appropriate privacy/security and public-health review. This prototype does not provide SMS delivery, official health-system integration, verified geocoding, or professional emergency dispatch out of the box.
