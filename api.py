"""Optional REST API for mobile clients or a separate React frontend.
Run: uvicorn backend.api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations
import csv, io
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from backend.config import MAX_UPLOAD_MB, APP_ENV, TOKEN_SECRET, CORS_ORIGINS
from backend.database import db_session
from backend.models import User
from backend.security import issue_token, verify_token
from backend.services import (initialize_database, authenticate, user_dict, create_complaint,
    list_complaints, get_complaint, create_user, list_users, assign_complaint,
    update_complaint, add_evidence, list_evidence, get_evidence_bytes, dashboard_summary, list_audit_logs, update_user_admin, get_active_user, ROLES)

app = FastAPI(title="SwasthyaGrid Civic Intelligence API", version="1.0.0", description="REST API for citizen reports, risk triage, officer workflow, and representative oversight.")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
bearer = HTTPBearer(auto_error=False)
if APP_ENV == "production" and ("replace-with" in TOKEN_SECRET.lower() or TOKEN_SECRET == "local-development-token-secret-change-before-deploy"):
    raise RuntimeError("Set a long random TOKEN_SECRET in production before starting the SwasthyaGrid API.")
initialize_database()

class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=200)

class ComplaintCreate(BaseModel):
    category: str
    description: str = Field(min_length=10, max_length=8000)
    location: str = Field(min_length=1, max_length=250)
    area: str = Field(default="Unassigned", max_length=120)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    severity: str = "Medium"
    allow_external_ai: bool = False

class ComplaintUpdate(BaseModel):
    status: str
    remarks: str = ""
    action_taken: str = ""

class AssignmentRequest(BaseModel):
    officer_id: Optional[int] = None
    representative_id: Optional[int] = None

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=10, max_length=200)
    role: str
    area: str = "Unassigned"


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    with db_session() as session:
        user = session.get(User, int(payload.get("sub", -1)))
        if not user or not user.active:
            raise HTTPException(status_code=401, detail="Account unavailable")
        if int(payload.get("ver", -1)) != user.token_version:
            raise HTTPException(status_code=401, detail="Token revoked; sign in again")
        return user_dict(user)


def require_roles(actor: dict, roles: set[str]) -> None:
    if actor.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def run_service(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "SwasthyaGrid API", "version": "1.0.0"}

@app.post("/api/auth/login")
def login(body: LoginRequest):
    actor = authenticate(body.username, body.password)
    if not actor:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = issue_token(actor["id"], actor["role"], actor["username"], actor.get("_token_version", 0))
    actor.pop("_token_version", None)
    return {"access_token": token, "token_type": "bearer", "expires_in": 28800, "user": actor}

@app.get("/api/me")
def me(actor: dict = Depends(current_user)):
    return actor

@app.get("/api/complaints")
def get_complaints(status_filter: str | None = None, area: str | None = None, limit: int = 500, actor: dict = Depends(current_user)):
    return run_service(list_complaints, actor, status=status_filter, area=area, limit=limit)

@app.post("/api/complaints", status_code=201)
def post_complaint(body: ComplaintCreate, actor: dict = Depends(current_user)):
    return run_service(create_complaint, actor, body.model_dump())

@app.get("/api/complaints/{complaint_id}")
def complaint_detail(complaint_id: str, actor: dict = Depends(current_user)):
    result = run_service(get_complaint, actor, complaint_id)
    if result is None: raise HTTPException(status_code=404, detail="Complaint not found")
    return result

@app.patch("/api/complaints/{complaint_id}/status")
def patch_complaint(complaint_id: str, body: ComplaintUpdate, actor: dict = Depends(current_user)):
    return run_service(update_complaint, actor, complaint_id, body.status, body.remarks, body.action_taken)

@app.post("/api/complaints/{complaint_id}/assignment")
def post_assignment(complaint_id: str, body: AssignmentRequest, actor: dict = Depends(current_user)):
    return run_service(assign_complaint, actor, complaint_id, body.officer_id, body.representative_id)

@app.post("/api/complaints/{complaint_id}/evidence", status_code=201)
async def post_evidence(complaint_id: str, file: UploadFile = File(...), note: str = Form(""), actor: dict = Depends(current_user)):
    content = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_MB} MB limit")
    complaint = run_service(get_complaint, actor, complaint_id)
    if complaint is None: raise HTTPException(status_code=404, detail="Complaint not found")
    result = run_service(add_evidence, actor, complaint_id, (file.filename or "evidence.bin", file.content_type or "application/octet-stream", content), note)
    return {"evidence": result, "message": "Evidence uploaded"}

@app.get("/api/complaints/{complaint_id}/evidence")
def get_evidence(complaint_id: str, actor: dict = Depends(current_user)):
    return run_service(list_evidence, actor, complaint_id)

@app.get("/api/evidence/{evidence_id}/download")
def download_evidence(evidence_id: int, actor: dict = Depends(current_user)):
    item = run_service(get_evidence_bytes, actor, evidence_id)
    if item is None: raise HTTPException(status_code=404, detail="Evidence not found")
    from fastapi.responses import Response
    return Response(content=item["data"], media_type=item["mime_type"], headers={"Content-Disposition": f'attachment; filename="{item["filename"].replace(chr(34), "")}"'})

@app.get("/api/reports/summary")
def report_summary(actor: dict = Depends(current_user)):
    return run_service(dashboard_summary, actor)

@app.get("/api/users")
def get_users(role: str | None = None, actor: dict = Depends(current_user)):
    return run_service(list_users, actor, role=role)

@app.post("/api/users", status_code=201)
def post_user(body: UserCreate, actor: dict = Depends(current_user)):
    return run_service(create_user, actor, body.username, body.full_name, body.password, body.role, body.area)

class UserUpdate(BaseModel):
    active: Optional[bool] = None
    new_password: Optional[str] = Field(default=None, min_length=10, max_length=200)
    area: Optional[str] = Field(default=None, max_length=120)
    full_name: Optional[str] = Field(default=None, max_length=160)

@app.patch("/api/users/{user_id}")
def patch_user(user_id: int, body: UserUpdate, actor: dict = Depends(current_user)):
    return run_service(update_user_admin, actor, user_id, body.active, body.new_password, body.area, body.full_name)

@app.get("/api/audit")
def audit(limit: int = 500, actor: dict = Depends(current_user)):
    return run_service(list_audit_logs, actor, limit=limit)

@app.get("/api/reports/export.csv")
def export_csv(actor: dict = Depends(current_user)):
    require_roles(actor, {"Admin", "Representative"})
    cases = run_service(list_complaints, actor, limit=2000)
    stream = io.StringIO()
    fields = ["id", "category", "description", "location", "area", "severity", "status", "priority_score", "risk_level", "ai_validation", "created_at", "updated_at"]
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader(); writer.writerows(cases)
    from fastapi.responses import Response
    return Response(content=stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=swasthyagrid_report.csv"})
