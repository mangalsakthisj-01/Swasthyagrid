"""Application services shared by the Streamlit UI and the REST API."""
from __future__ import annotations
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import or_, select, func, inspect, text
from backend.config import ALLOW_DEMO_LOGIN, BOOTSTRAP_ADMIN_PASSWORD
from backend.database import Base, engine, db_session
from backend.models import User, Complaint, Evidence, AuditLog
from backend.security import hash_password, verify_password
from backend.triage import assess_complaint

ROLES = {"Citizen", "Field Officer", "Admin", "Representative"}
STATUSES = {"Submitted", "Under Review", "Assigned", "In Progress", "Escalated", "Resolved", "Reopened", "Rejected"}
CATEGORIES = ["Water & Drainage", "Road & Transport", "Waste & Sanitation", "Public Health", "Electricity & Lighting", "Other Civic Issue"]
SEVERITIES = ["Low", "Medium", "High", "Critical"]


def user_dict(user: User) -> dict:
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "area": user.area, "active": user.active, "created_at": user.created_at.isoformat() if user.created_at else None}


def complaint_dict(c: Complaint, include_private: bool = True) -> dict:
    return {
        "id": c.id, "citizen_id": c.citizen_id,
        "citizen_name": c.citizen_name if include_private else "Citizen (privacy protected)",
        "category": c.category, "description": c.description, "location": c.location, "area": c.area,
        "latitude": c.latitude, "longitude": c.longitude, "severity": c.severity, "status": c.status,
        "priority_score": c.priority_score, "risk_level": c.risk_level, "ai_validation": c.ai_validation,
        "ai_confidence": c.ai_confidence, "ai_reason": c.ai_reason, "triage_provider": c.triage_provider,
        "review_required": c.review_required, "critical_override": c.critical_override,
        "assigned_officer_id": c.assigned_officer_id, "representative_id": c.representative_id,
        "officer_remarks": c.officer_remarks, "action_taken": c.action_taken,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
    }


def _enriched_complaint_dict(session, c: Complaint, include_private: bool = True) -> dict:
    payload = complaint_dict(c, include_private=include_private)
    officer = session.get(User, c.assigned_officer_id) if c.assigned_officer_id else None
    rep = session.get(User, c.representative_id) if c.representative_id else None
    payload["assigned_officer_name"] = officer.full_name if officer and officer.active else None
    payload["representative_name"] = rep.full_name if rep and rep.active else None
    return payload


def _audit(session, actor: dict | None, action: str, complaint_id: str | None = None, detail: str = "") -> None:
    session.add(AuditLog(actor_id=(actor or {}).get("id"), actor_username=(actor or {}).get("username", "system"), action=action, complaint_id=complaint_id, detail=detail[:3000]))


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    # Small forward-compatible migration for installations created before token revocation was added.
    existing_columns = {col["name"] for col in inspect(engine).get_columns("users")} if inspect(engine).has_table("users") else set()
    if existing_columns and "token_version" not in existing_columns:
        if engine.dialect.name == "sqlite":
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
        elif engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"))
    with db_session() as session:
        existing = session.scalar(select(func.count()).select_from(User)) or 0
        if existing == 0:
            if ALLOW_DEMO_LOGIN:
                seed_users = [
                    ("admin", "SwasthyaGrid Admin", "Admin@12345", "Admin", "All Areas"),
                    ("officer", "Demo Field Officer", "Officer@12345", "Field Officer", "Ward 12"),
                    ("representative", "Demo Representative", "Rep@123456", "Representative", "Ward 12"),
                    ("citizen", "Demo Citizen", "Citizen@12345", "Citizen", "Ward 12"),
                ]
                for username, full_name, password, role, area in seed_users:
                    session.add(User(username=username, full_name=full_name, password_hash=hash_password(password), role=role, area=area, active=True))
                session.flush()
            elif BOOTSTRAP_ADMIN_PASSWORD:
                session.add(User(username="admin", full_name="SwasthyaGrid Administrator", password_hash=hash_password(BOOTSTRAP_ADMIN_PASSWORD), role="Admin", area="All Areas", active=True))
                session.flush()
        session.flush()
        # Seed clearly labelled fictional demo cases for a populated first run.
        count = session.scalar(select(func.count()).select_from(Complaint)) or 0
        if ALLOW_DEMO_LOGIN and count == 0:
            users = {u.username: u for u in session.scalars(select(User)).all()}
            samples = [
                ("Water & Drainage", "Water is pooling near a blocked roadside drain after rain.", "Near Market Road", 11.0168, 76.9558, "High", "In Progress", 84, "High", users["officer"].id),
                ("Waste & Sanitation", "Garbage bags are accumulating beside the public bin.", "Ward 12 Main Street", 11.0184, 76.9581, "Medium", "Submitted", 52, "Medium", None),
                ("Road & Transport", "A large pothole is affecting two-wheelers near the bus stop.", "Central Bus Stop", 11.0148, 76.9600, "High", "Assigned", 80, "High", users["officer"].id),
                ("Public Health", "Several residents report mosquito breeding around stagnant water.", "Ward 12 East", 11.0212, 76.9514, "High", "Escalated", 88, "High", users["officer"].id),
                ("Electricity & Lighting", "Streetlight is not working at the pedestrian crossing.", "School Junction", 11.0124, 76.9532, "Low", "Resolved", 28, "Low", users["officer"].id),
                ("Water & Drainage", "A roadside water pipe appears to be leaking continuously.", "Library Lane", 11.0201, 76.9628, "Medium", "Under Review", 56, "Medium", None),
            ]
            for idx, row in enumerate(samples):
                category, desc, loc, lat, lon, sev, status, score, risk, officer_id = row
                is_critical = status == "Escalated"
                c = Complaint(id=str(uuid4()), citizen_id=users["citizen"].id, citizen_name=users["citizen"].full_name,
                    category=category, description=desc, location=loc, area="Ward 12", latitude=lat, longitude=lon,
                    severity=sev, status=status, priority_score=score, risk_level=risk, ai_validation="Demo - human review", ai_confidence=62,
                    ai_reason="Fictional sample case for demonstration only.", triage_provider="Demo data", review_required=True,
                    critical_override=is_critical, assigned_officer_id=officer_id, representative_id=users["representative"].id,
                    officer_remarks="Demo data only", action_taken="Sample action record" if status == "Resolved" else "",
                    created_at=datetime.utcnow() - timedelta(hours=idx * 9), updated_at=datetime.utcnow() - timedelta(hours=idx * 2))
                session.add(c)
            _audit(session, None, "DEMO_DATA_SEEDED", detail="Fictional demo cases created. Do not use these as real public reports.")


def authenticate(username: str, password: str) -> dict | None:
    with db_session() as session:
        user = session.scalar(select(User).where(User.username == username.strip().lower()))
        if not user or not user.active or not verify_password(password, user.password_hash):
            return None
        result = user_dict(user)
        result["_token_version"] = user.token_version
        return result


def get_active_user(user_id: int, expected_token_version: int | None = None) -> dict | None:
    with db_session() as session:
        user = session.get(User, int(user_id))
        if not user or not user.active:
            return None
        if expected_token_version is not None and user.token_version != int(expected_token_version):
            return None
        result = user_dict(user)
        result["_token_version"] = user.token_version
        return result


def create_user(actor: dict, username: str, full_name: str, password: str, role: str, area: str) -> dict:
    if actor.get("role") != "Admin":
        raise PermissionError("Only Admin can create accounts.")
    username = username.strip().lower()
    full_name, area = full_name.strip(), area.strip() or "Unassigned"
    if not username or len(username) < 3 or not username.replace("_", "").replace(".", "").isalnum():
        raise ValueError("Username must be at least 3 characters and use letters, numbers, underscore or dot.")
    if role not in ROLES:
        raise ValueError("Invalid role.")
    if not full_name:
        raise ValueError("Full name is required.")
    password_hash = hash_password(password)
    with db_session() as session:
        if session.scalar(select(User).where(User.username == username)):
            raise ValueError("That username already exists.")
        user = User(username=username, full_name=full_name, password_hash=password_hash, role=role, area=area, active=True)
        session.add(user); session.flush()
        _audit(session, actor, "USER_CREATED", detail=f"Created account {username} with role {role} for area {area}.")
        return user_dict(user)


def list_users(actor: dict, role: str | None = None) -> list[dict]:
    if actor.get("role") != "Admin":
        raise PermissionError("Only Admin can manage users.")
    with db_session() as session:
        stmt = select(User).order_by(User.role, User.area, User.full_name)
        if role and role in ROLES:
            stmt = stmt.where(User.role == role)
        return [user_dict(u) for u in session.scalars(stmt).all()]


def create_complaint(actor: dict, values: dict, file_tuple: tuple[str, str, bytes] | None = None) -> dict:
    if actor.get("role") not in {"Citizen", "Admin"}:
        raise PermissionError("Only citizens or Admin can submit a complaint.")
    category = str(values.get("category", "Other Civic Issue"))
    if category not in CATEGORIES:
        raise ValueError("Choose a valid complaint category.")
    description = str(values.get("description", "")).strip()
    location = str(values.get("location", "")).strip()
    area = str(values.get("area", actor.get("area", "Unassigned"))).strip() or "Unassigned"
    if len(description) < 10:
        raise ValueError("Please describe the issue in at least 10 characters.")
    if not location:
        raise ValueError("Location or landmark is required.")
    severity = str(values.get("severity", "Medium")).title()
    if severity not in SEVERITIES:
        severity = "Medium"
    lat, lon = values.get("latitude"), values.get("longitude")
    try:
        lat = None if lat in (None, "") else float(lat)
        lon = None if lon in (None, "") else float(lon)
    except (TypeError, ValueError):
        raise ValueError("Latitude and longitude must be numbers.")
    if lat is not None and not -90 <= lat <= 90: raise ValueError("Latitude must be between -90 and 90.")
    if lon is not None and not -180 <= lon <= 180: raise ValueError("Longitude must be between -180 and 180.")
    media_data, mime = (file_tuple[2], file_tuple[1]) if file_tuple else (None, None)
    triage = assess_complaint(category, description, severity, media_data, mime, allow_external_ai=bool(values.get("allow_external_ai", False)))
    complaint_id = str(uuid4())
    with db_session() as session:
        citizen = session.get(User, int(actor["id"]))
        if not citizen or not citizen.active:
            raise PermissionError("Your account is inactive.")
        officers = list(session.scalars(select(User).where(User.role == "Field Officer", User.active.is_(True)).order_by(User.id)).all())
        reps = list(session.scalars(select(User).where(User.role == "Representative", User.active.is_(True)).order_by(User.id)).all())
        officer = next((u for u in officers if u.area.lower() == area.lower()), officers[0] if officers else None)
        rep = next((u for u in reps if u.area.lower() == area.lower()), reps[0] if reps else None)
        critical = bool(triage["critical_override"])
        c = Complaint(id=complaint_id, citizen_id=citizen.id, citizen_name=citizen.full_name, category=category,
            description=description, location=location, area=area, latitude=lat, longitude=lon,
            severity=triage["severity"], status="Escalated" if critical else "Submitted",
            priority_score=triage["priority_score"], risk_level=triage["risk_level"], ai_validation=triage["ai_validation"],
            ai_confidence=triage["ai_confidence"], ai_reason=triage["ai_reason"], triage_provider=triage["triage_provider"],
            review_required=triage["review_required"], critical_override=critical,
            assigned_officer_id=officer.id if critical and officer else None,
            representative_id=rep.id if critical and rep else None)
        session.add(c)
        if file_tuple:
            filename, content_type, data = file_tuple
            session.add(Evidence(complaint_id=complaint_id, uploaded_by=citizen.id, filename=filename[:255], mime_type=content_type or "application/octet-stream", data=data, note="Citizen-submitted evidence"))
        session.flush()
        _audit(session, actor, "COMPLAINT_CREATED", complaint_id, f"Category={category}; priority={triage['priority_score']}; critical={critical}; provider={triage['triage_provider']}.")
        return complaint_dict(c)


def _scope_stmt(actor: dict):
    role = actor.get("role")
    if role == "Citizen":
        return Complaint.citizen_id == int(actor["id"])
    if role == "Field Officer":
        return or_(Complaint.assigned_officer_id == int(actor["id"]), Complaint.area == actor.get("area", ""))
    if role == "Representative":
        return or_(Complaint.representative_id == int(actor["id"]), Complaint.area == actor.get("area", ""))
    return None


def list_complaints(actor: dict, status: str | None = None, area: str | None = None, limit: int = 500) -> list[dict]:
    with db_session() as session:
        stmt = select(Complaint).order_by(Complaint.priority_score.desc(), Complaint.created_at.desc())
        scope = _scope_stmt(actor)
        if scope is not None:
            stmt = stmt.where(scope)
        if status and status in STATUSES:
            stmt = stmt.where(Complaint.status == status)
        if area and actor.get("role") == "Admin":
            stmt = stmt.where(Complaint.area == area)
        results = session.scalars(stmt.limit(max(1, min(limit, 2000)))).all()
        private = actor.get("role") not in {"Representative"}
        return [_enriched_complaint_dict(session, c, include_private=private) for c in results]


def get_complaint(actor: dict, complaint_id: str, allow_private: bool = True) -> dict | None:
    with db_session() as session:
        c = session.get(Complaint, complaint_id)
        if not c: return None
        scope = _scope_stmt(actor)
        if scope is not None and not session.scalar(select(Complaint.id).where(Complaint.id == complaint_id, scope)):
            raise PermissionError("You are not allowed to view this complaint.")
        return _enriched_complaint_dict(session, c, include_private=allow_private and actor.get("role") != "Representative")


def assign_complaint(actor: dict, complaint_id: str, officer_id: int | None, representative_id: int | None = None) -> dict:
    if actor.get("role") != "Admin":
        raise PermissionError("Only Admin can assign complaints.")
    with db_session() as session:
        c = session.get(Complaint, complaint_id)
        if not c: raise ValueError("Complaint not found.")
        officer = session.get(User, officer_id) if officer_id else None
        rep = session.get(User, representative_id) if representative_id else None
        if officer and (officer.role != "Field Officer" or not officer.active): raise ValueError("Select an active Field Officer.")
        if rep and (rep.role != "Representative" or not rep.active): raise ValueError("Select an active Representative.")
        c.assigned_officer_id = officer.id if officer else None
        c.representative_id = rep.id if rep else c.representative_id
        if c.status == "Submitted": c.status = "Assigned" if officer else "Under Review"
        c.updated_at = datetime.utcnow()
        _audit(session, actor, "COMPLAINT_ASSIGNED", complaint_id, f"Officer ID={officer_id}; Representative ID={representative_id}.")
        return complaint_dict(c)


def update_complaint(actor: dict, complaint_id: str, status: str, remarks: str = "", action_taken: str = "", file_tuple: tuple[str, str, bytes] | None = None) -> dict:
    if status not in STATUSES: raise ValueError("Invalid status.")
    with db_session() as session:
        c = session.get(Complaint, complaint_id)
        if not c: raise ValueError("Complaint not found.")
        role, aid = actor.get("role"), int(actor.get("id", -1))
        if role == "Citizen":
            if c.citizen_id != aid or status != "Reopened" or c.status != "Resolved":
                raise PermissionError("Citizens may only reopen their own resolved complaints.")
        elif role == "Field Officer":
            if c.assigned_officer_id != aid and c.area.lower() != str(actor.get("area", "")).lower():
                raise PermissionError("This complaint is outside your assigned jurisdiction.")
            if status == "Rejected": raise PermissionError("Field Officers cannot reject complaints.")
        elif role == "Representative":
            if c.representative_id != aid and c.area.lower() != str(actor.get("area", "")).lower():
                raise PermissionError("This complaint is outside your oversight jurisdiction.")
            if status not in {"Escalated", "Under Review", "Assigned"}:
                raise PermissionError("Representatives can request action or escalate; operational closure belongs to the assigned team.")
        elif role != "Admin":
            raise PermissionError("Not authorized.")
        if status == "Resolved" and not (action_taken.strip() or c.action_taken.strip()):
            raise ValueError("Add an action-taken note before marking a complaint resolved.")
        old_status = c.status
        c.status = status
        c.officer_remarks = remarks.strip()[:5000] if remarks.strip() else c.officer_remarks
        c.action_taken = action_taken.strip()[:5000] if action_taken.strip() else c.action_taken
        c.updated_at = datetime.utcnow()
        c.resolved_at = datetime.utcnow() if status == "Resolved" else (None if status == "Reopened" else c.resolved_at)
        if status == "Escalated": c.critical_override = c.critical_override or c.priority_score >= 80
        if file_tuple:
            filename, content_type, data = file_tuple
            session.add(Evidence(complaint_id=c.id, uploaded_by=aid, filename=filename[:255], mime_type=content_type or "application/octet-stream", data=data, note="Field/oversight evidence"))
        session.flush()
        _audit(session, actor, "COMPLAINT_STATUS_CHANGED", c.id, f"{old_status} -> {status}; remarks={'yes' if remarks.strip() else 'no'}; evidence={'yes' if file_tuple else 'no'}.")
        return complaint_dict(c, include_private=role != "Representative")


def list_evidence(actor: dict, complaint_id: str) -> list[dict]:
    # Permissions are checked through complaint retrieval first.
    get_complaint(actor, complaint_id, allow_private=False)
    with db_session() as session:
        rows = session.scalars(select(Evidence).where(Evidence.complaint_id == complaint_id).order_by(Evidence.created_at.desc())).all()
        return [{"id": e.id, "filename": e.filename, "mime_type": e.mime_type, "note": e.note, "created_at": e.created_at.isoformat(), "uploaded_by": e.uploaded_by} for e in rows]


def get_evidence_bytes(actor: dict, evidence_id: int) -> dict | None:
    with db_session() as session:
        e = session.get(Evidence, evidence_id)
        if not e: return None
        c = session.get(Complaint, e.complaint_id)
        if not c: return None
        scope = _scope_stmt(actor)
        if scope is not None and not session.scalar(select(Complaint.id).where(Complaint.id == c.id, scope)):
            raise PermissionError("You cannot view this attachment.")
        return {"filename": e.filename, "mime_type": e.mime_type, "data": e.data}


def list_audit_logs(actor: dict, limit: int = 500) -> list[dict]:
    if actor.get("role") != "Admin": raise PermissionError("Only Admin can view the audit ledger.")
    with db_session() as session:
        rows = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 2000))).all()
        return [{"id": x.id, "actor_username": x.actor_username, "action": x.action, "complaint_id": x.complaint_id, "detail": x.detail, "created_at": x.created_at.isoformat()} for x in rows]


def dashboard_summary(actor: dict) -> dict:
    cases = list_complaints(actor, limit=2000)
    statuses = {s: sum(1 for c in cases if c["status"] == s) for s in sorted(STATUSES)}
    return {"total": len(cases), "open": sum(1 for c in cases if c["status"] not in {"Resolved", "Rejected"}),
            "resolved": statuses.get("Resolved", 0), "escalated": statuses.get("Escalated", 0),
            "critical": sum(1 for c in cases if c["risk_level"] == "Critical" or c["critical_override"]),
            "review_required": sum(1 for c in cases if c["review_required"]), "statuses": statuses,
            "by_category": {cat: sum(1 for c in cases if c["category"] == cat) for cat in CATEGORIES}}


def add_evidence(actor: dict, complaint_id: str, file_tuple: tuple[str, str, bytes], note: str = "") -> dict:
    """Attach a file without changing case status; enforce the same jurisdiction checks."""
    with db_session() as session:
        c = session.get(Complaint, complaint_id)
        if not c: raise ValueError("Complaint not found.")
        role, aid = actor.get("role"), int(actor.get("id", -1))
        permitted = role == "Admin"
        if role == "Citizen": permitted = c.citizen_id == aid
        elif role == "Field Officer": permitted = c.assigned_officer_id == aid or c.area.lower() == str(actor.get("area", "")).lower()
        elif role == "Representative": permitted = c.representative_id == aid or c.area.lower() == str(actor.get("area", "")).lower()
        if not permitted: raise PermissionError("You cannot attach evidence to this complaint.")
        filename, content_type, data = file_tuple
        evidence = Evidence(complaint_id=c.id, uploaded_by=aid, filename=filename[:255], mime_type=content_type or "application/octet-stream", data=data, note=note.strip()[:2000])
        session.add(evidence)
        c.updated_at = datetime.utcnow()
        session.flush()
        _audit(session, actor, "EVIDENCE_ADDED", c.id, f"Attachment {filename[:255]} added.")
        return {"id": evidence.id, "complaint_id": c.id, "filename": evidence.filename, "mime_type": evidence.mime_type, "created_at": evidence.created_at.isoformat() if evidence.created_at else datetime.utcnow().isoformat()}


def update_user_admin(actor: dict, user_id: int, active: bool | None = None, new_password: str | None = None, area: str | None = None, full_name: str | None = None) -> dict:
    if actor.get("role") != "Admin":
        raise PermissionError("Only Admin can manage user accounts.")
    if new_password is not None and new_password != "":
        password_hash = hash_password(new_password)
    else:
        password_hash = None
    with db_session() as session:
        user = session.get(User, user_id)
        if not user: raise ValueError("User not found.")
        if active is False and user.id == int(actor["id"]):
            raise ValueError("You cannot deactivate your own active session.")
        if active is False and user.role == "Admin" and user.active:
            other_admins = session.scalar(select(func.count()).select_from(User).where(User.role == "Admin", User.active.is_(True), User.id != user.id)) or 0
            if other_admins == 0: raise ValueError("The system must retain at least one active Admin.")
        if active is not None and user.active != bool(active):
            user.active = bool(active)
            user.token_version += 1
        if password_hash:
            user.password_hash = password_hash
            user.token_version += 1
        if area is not None and area.strip(): user.area = area.strip()[:120]
        if full_name is not None and full_name.strip(): user.full_name = full_name.strip()[:160]
        session.flush()
        _audit(session, actor, "USER_UPDATED", detail=f"Updated account {user.username}; active={user.active}; password_reset={bool(password_hash)}.")
        return user_dict(user)


def get_public_hotspots(area: str | None = None, threshold: int = 3) -> list[dict]:
    """Return aggregate-only clusters; never return citizen identities, descriptions, or exact locations."""
    threshold = max(3, min(int(threshold), 100))
    with db_session() as session:
        rows = session.scalars(select(Complaint)).all()
        groups: dict[tuple[str, str], list[Complaint]] = {}
        for c in rows:
            if area and c.area.casefold() != area.casefold():
                continue
            groups.setdefault((c.area, c.category), []).append(c)
        result = []
        for (group_area, category), items in groups.items():
            if len(items) < threshold:
                continue
            result.append({
                "area": group_area, "category": category, "reports": len(items),
                "open_reports": sum(1 for c in items if c.status not in {"Resolved", "Rejected"}),
                "high_priority_reports": sum(1 for c in items if c.priority_score >= 80),
                "signal": "Investigate cluster",
            })
        return sorted(result, key=lambda x: (x["high_priority_reports"], x["reports"]), reverse=True)
