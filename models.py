"""Database models for citizens, civic cases, attachments, and immutable-style audit events."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    area: Mapped[str] = mapped_column(String(120), default="Unassigned", nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    citizen_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    citizen_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(250), nullable=False)
    area: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="Medium", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="Submitted", nullable=False, index=True)
    priority_score: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="Medium", nullable=False)
    ai_validation: Mapped[str] = mapped_column(String(40), default="Needs review", nullable=False)
    ai_confidence: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    ai_reason: Mapped[str] = mapped_column(Text, default="Rule-based assessment", nullable=False)
    triage_provider: Mapped[str] = mapped_column(String(40), default="Rules", nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    critical_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assigned_officer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    representative_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    officer_remarks: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action_taken: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[str] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_username: Mapped[str] = mapped_column(String(80), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    complaint_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
