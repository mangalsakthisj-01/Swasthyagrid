"""Backend smoke test: run with `python tests/smoke_test.py`. Uses a disposable SQLite DB."""
import os, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + Path(tmp.name).as_posix()
os.environ["ALLOW_DEMO_LOGIN"] = "true"
os.environ["TOKEN_SECRET"] = "test-only-random-secret-change-this"

from backend.services import (initialize_database, authenticate, create_complaint, list_complaints,
                              assign_complaint, update_complaint, add_evidence, list_evidence,
                              create_user, dashboard_summary, update_user_admin)
from backend.security import issue_token, verify_token

initialize_database()
actors = {name: authenticate(name, pw) for name, pw in {
    "admin": "Admin@12345", "officer": "Officer@12345", "representative": "Rep@123456", "citizen": "Citizen@12345"
}.items()}
assert all(actors.values()), "Role login failed"

critical = create_complaint(actors["citizen"], {
    "category": "Road & Transport", "description": "Road cave-in near the school gate; urgent safety inspection needed.",
    "location": "School Gate", "area": "Ward 12", "severity": "Medium"
}, ("proof.jpg", "image/jpeg", b"sample binary"))
assert critical["status"] == "Escalated" and critical["critical_override"]
add_evidence(actors["officer"], critical["id"], ("inspection.jpg", "image/jpeg", b"sample after"), "Inspection note")
assert len(list_evidence(actors["officer"], critical["id"])) == 2

normal = create_complaint(actors["citizen"], {
    "category": "Water & Drainage", "description": "Water is leaking from a pipe next to the public walkway.",
    "location": "Library Lane", "area": "Ward 12", "severity": "Medium"
})
assigned = assign_complaint(actors["admin"], normal["id"], actors["officer"]["id"], actors["representative"]["id"])
assert assigned["assigned_officer_id"] == actors["officer"]["id"]
resolved = update_complaint(actors["officer"], normal["id"], "Resolved", "Pipe inspected", "Pipe joint repaired")
assert resolved["status"] == "Resolved"

created = create_user(actors["admin"], "testcitizen", "Test Citizen", "Another-Strong-Password", "Citizen", "Ward 2")
assert authenticate("testcitizen", "Another-Strong-Password")
updated = update_user_admin(actors["admin"], created["id"], active=False)
assert updated["active"] is False
summary = dashboard_summary(actors["admin"])
assert summary["total"] >= 8

token = issue_token(actors["admin"]["id"], actors["admin"]["role"], actors["admin"]["username"])
assert verify_token(token) is not None
assert verify_token(token + "x") is None
print("PASS: four roles, critical bypass, attachment storage, assignment, resolution, user lifecycle, summary, and API token signatures.")
try: os.unlink(tmp.name)
except OSError: pass
