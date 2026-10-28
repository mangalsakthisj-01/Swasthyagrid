from __future__ import annotations
from datetime import datetime
import pandas as pd
import plotly.express as px
import streamlit as st

from backend.config import ALLOW_DEMO_LOGIN, MAX_UPLOAD_MB, GEMINI_API_KEY, GROQ_API_KEY, DATABASE_URL_SETTING, APP_ENV
from backend.services import (
    initialize_database, authenticate, get_active_user, create_complaint, list_complaints, get_complaint,
    create_user, list_users, assign_complaint, update_complaint, add_evidence,
    list_evidence, get_evidence_bytes, dashboard_summary, list_audit_logs, update_user_admin,
    CATEGORIES, ROLES, STATUSES, SEVERITIES, get_public_hotspots,
)

st.set_page_config(page_title="SwasthyaGrid | Civic Intelligence", page_icon="🌐", layout="wide", initial_sidebar_state="expanded")
initialize_database()

st.markdown("""
<style>
:root { --sg-ink:#10233f; --sg-muted:#60718a; --sg-blue:#2563eb; --sg-teal:#0f9b8e; }
[data-testid="stAppViewContainer"] { background: linear-gradient(180deg, #f6f9ff 0%, #f7fafc 48%, #f3f7fa 100%); }
[data-testid="stSidebar"] { background: #10233f; }
[data-testid="stSidebar"] * { color: #edf4ff !important; }
[data-testid="stSidebar"] input { color: #10233f !important; }
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1500px; }
.sg-hero { background: linear-gradient(120deg,#10233f,#17406f 72%,#0f766e); padding: 1.65rem 1.8rem; border-radius: 22px; color: white; margin-bottom: 1rem; box-shadow: 0 10px 32px rgba(16,35,63,.12); }
.sg-hero h1 { margin: 0; color: white; font-size: 2rem; letter-spacing: -.02em; }
.sg-hero p { margin: .45rem 0 0 0; color: #d5e7ff; }
.sg-overline { color: #69e3d2; font-size: .76rem; font-weight: 800; letter-spacing: .15em; text-transform: uppercase; }
[data-testid="stMetric"] { background:white; border:1px solid #e3eaf3; padding: 1rem 1.05rem; border-radius: 16px; box-shadow: 0 3px 12px rgba(24,48,77,.04); }
div[data-testid="stForm"] { background: white; padding: 1rem 1.1rem; border:1px solid #e3eaf3; border-radius: 16px; }
[data-testid="stDataFrame"] { border: 1px solid #e3eaf3; border-radius: 12px; overflow: hidden; }
.stButton button, .stDownloadButton button { border-radius: 10px; font-weight: 650; }
hr { border-color: #e4eaf2; }
</style>
""", unsafe_allow_html=True)


def hero(title: str, subtitle: str, role_label: str = "CIVIC INTELLIGENCE"):
    st.markdown(f'<div class="sg-hero"><div class="sg-overline">{role_label}</div><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def safe_df(cases: list[dict], columns: list[str] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(cases)
    if columns:
        available = [c for c in columns if c in df.columns]
        return df[available]
    return df


def case_label(c: dict) -> str:
    return f"{c['id'][:8]} · {c['category']} · {c['status']} · {c['area']}"


def show_metrics(summary: dict, names: tuple[str, ...] = ("total", "open", "escalated", "resolved")):
    title_map = {"total": "Total reports", "open": "Open cases", "escalated": "Escalated", "resolved": "Resolved", "critical": "Critical risk", "review_required": "Awaiting review"}
    cols = st.columns(len(names))
    for col, key in zip(cols, names):
        col.metric(title_map.get(key, key.replace("_", " ").title()), summary.get(key, 0))


def show_map(cases: list[dict], title: str = "Reported issue locations"):
    located = [c for c in cases if c.get("latitude") is not None and c.get("longitude") is not None]
    st.subheader(title)
    if located:
        mdf = pd.DataFrame([{"lat": c["latitude"], "lon": c["longitude"], "category": c["category"], "status": c["status"], "area": c["area"]} for c in located])
        st.map(mdf, latitude="lat", longitude="lon", size=50, color="#0f9b8e")
        st.caption(f"Showing {len(mdf)} reports with coordinates. Map markers represent reports, not confirmed disease cases.")
    else:
        st.info("No reports have map coordinates yet. Add latitude and longitude when submitting a report to enable geographic views.")


def show_evidence(actor: dict, complaint_id: str):
    try:
        items = list_evidence(actor, complaint_id)
    except Exception as exc:
        st.warning(str(exc)); return
    if not items:
        st.caption("No files attached to this report.")
        return
    st.markdown("**Evidence attachments**")
    for item in items:
        try:
            content = get_evidence_bytes(actor, item["id"])
            if not content:
                continue
            a, b = st.columns([3, 1])
            with a:
                st.write(f"📎 {item['filename']}")
                if item["mime_type"].startswith("image/"):
                    st.image(content["data"], width=360)
                else:
                    st.caption(f"{item['mime_type']} · Uploaded {item['created_at'][:19]}")
            with b:
                st.download_button("Download", content["data"], file_name=item["filename"], mime=item["mime_type"], key=f"download_{item['id']}")
        except Exception:
            st.caption(f"Attachment: {item['filename']}")


def csv_download(cases: list[dict], filename: str, label: str = "Download CSV report"):
    df = pd.DataFrame(cases)
    st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), filename, "text/csv", key=f"csv_{filename}")


def logout():
    st.session_state.pop("sg_user", None)
    st.rerun()


def login_screen():
    st.markdown("<div style='max-width:760px;margin:2rem auto 0 auto'>", unsafe_allow_html=True)
    hero("SwasthyaGrid", "Civic intelligence for safer neighbourhoods, faster response, and accountable public services.")
    lcol, rcol = st.columns([1.1, .9], gap="large")
    with lcol:
        st.subheader("Sign in to your workspace")
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("User ID", placeholder="Enter your username", autocomplete="username")
            password = st.text_input("Password", type="password", placeholder="Enter your password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in securely", type="primary", use_container_width=True)
        if submitted:
            if not username.strip() or not password:
                st.error("Enter both username and password.")
            else:
                actor = authenticate(username, password)
                if actor:
                    st.session_state["sg_user"] = actor
                    st.rerun()
                else:
                    st.error("Invalid credentials, or this account is inactive.")
        st.caption("Access is role-based. Your account controls what data and actions are available.")
    with rcol:
        st.markdown("### One system, four perspectives")
        st.markdown("**🏠 Citizen** · Report issues and follow progress\n\n**🦺 Field Officer** · Investigate, document, and resolve\n\n**🛡️ Admin** · Manage routing, users, analytics, and audit\n\n**🏛️ Representative** · Review ward-level outcomes and oversight")
        if ALLOW_DEMO_LOGIN:
            with st.expander("Demo accounts — local demonstration only", expanded=True):
                st.warning("These shared example credentials are for demonstration only. Disable demo mode and configure a private database before public use.")
                st.code("Admin:          admin / Admin@12345\nField Officer:  officer / Officer@12345\nRepresentative: representative / Rep@123456\nCitizen:        citizen / Citizen@12345", language="text")
        elif not BOOTSTRAP_PASSWORD_AVAILABLE:
            st.info("For a fresh production database, set BOOTSTRAP_ADMIN_PASSWORD in your hosting secrets, then restart the app.")
    st.markdown("</div>", unsafe_allow_html=True)


# Config state used only for the fresh-install instruction.
BOOTSTRAP_PASSWORD_AVAILABLE = bool(__import__("backend.config", fromlist=["BOOTSTRAP_ADMIN_PASSWORD"]).BOOTSTRAP_ADMIN_PASSWORD)


def citizen_dashboard(actor: dict):
    hero(f"Welcome, {actor['full_name']}", "Report local issues, receive area alerts, and keep your service requests accountable.", "CITIZEN PORTAL")
    cases = list_complaints(actor)
    summary = dashboard_summary(actor)
    show_metrics(summary, ("total", "open", "resolved"))
    report_tab, tracking_tab, alerts_tab = st.tabs(["＋ Raise a complaint", "◷ My reports & tracking", "⌁ Local alerts"])
    with report_tab:
        st.subheader("Tell us what needs attention")
        st.caption(f"Attach evidence (photo, short video, or audio). Upload limit: {MAX_UPLOAD_MB} MB per file. Do not upload sensitive medical records or other people's private information.")
        with st.form("citizen_report_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            category = col1.selectbox("Issue category", CATEGORIES)
            severity = col2.selectbox("Perceived urgency", SEVERITIES, index=1, help="The system may raise priority for safety signals; AI recommendations are reviewed by people.")
            desc = st.text_area("Describe the issue", placeholder="What happened, when did you notice it, and who may be affected?", height=130, max_chars=8000)
            col3, col4 = st.columns(2)
            location = col3.text_input("Location / landmark", placeholder="Street, school, market, junction…")
            area = col4.text_input("Ward / locality", value=actor.get("area", "Unassigned"))
            c5, c6 = st.columns(2)
            lat = c5.number_input("Latitude (optional)", value=0.0, format="%.6f", help="Leave 0 if unknown; a value of 0 is treated as not supplied.")
            lon = c6.number_input("Longitude (optional)", value=0.0, format="%.6f", help="Leave 0 if unknown; a value of 0 is treated as not supplied.")
            uploaded = st.file_uploader("Add supporting media (optional)", type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "mp3", "wav", "m4a"], key="citizen_upload")
            confirm = st.checkbox("I confirm this report is submitted in good faith and does not contain unnecessary personal information.")
            allow_external_ai = False
            if GEMINI_API_KEY or GROQ_API_KEY:
                allow_external_ai = st.checkbox("I consent to sending the complaint text and any attached image to the configured AI provider for an advisory triage assessment.", value=False)
            submit = st.form_submit_button("Submit complaint", type="primary", use_container_width=True)
        if submit:
            if not confirm:
                st.error("Please confirm the statement before submitting.")
            elif uploaded is not None and uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
                st.error(f"The file exceeds the {MAX_UPLOAD_MB} MB limit.")
            else:
                ftuple = (uploaded.name, uploaded.type or "application/octet-stream", uploaded.getvalue()) if uploaded is not None else None
                try:
                    new_case = create_complaint(actor, {"category": category, "severity": severity, "description": desc, "location": location, "area": area,
                        "latitude": lat if lat != 0 else None, "longitude": lon if lon != 0 else None, "allow_external_ai": allow_external_ai}, ftuple)
                    if new_case["critical_override"]:
                        st.error(f"Urgent safety trigger detected. Case {new_case['id'][:8]} has bypassed the normal queue and was marked Escalated.")
                    else:
                        st.success(f"Complaint submitted. Your case reference is {new_case['id'][:8]}.")
                    st.info(f"Triage: {new_case['ai_validation']} · Priority {new_case['priority_score']}/100 · Source: {new_case['triage_provider']}. This is advisory and not proof of validity.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    with tracking_tab:
        st.subheader("Your complaint timeline")
        if not cases:
            st.info("No reports yet. Use the first tab to submit your first complaint.")
        else:
            df = safe_df(cases, ["id", "category", "area", "location", "severity", "status", "risk_level", "priority_score", "assigned_officer_name", "representative_name", "created_at", "updated_at"])
            df["id"] = df["id"].str.slice(0, 8)
            st.dataframe(df, use_container_width=True, hide_index=True)
            opts = {case_label(c): c for c in cases}
            selected = st.selectbox("Open a report", list(opts), key="citizen_case_select")
            case = opts[selected]
            st.markdown(f"**Case {case['id'][:8]} · {case['category']}**")
            st.write(case["description"])
            st.caption(f"Triage note: {case['ai_reason']}")
            if case.get("officer_remarks"): st.info(f"Latest remarks: {case['officer_remarks']}")
            if case.get("action_taken"): st.success(f"Action taken: {case['action_taken']}")
            show_evidence(actor, case["id"])
            if case["status"] == "Resolved":
                with st.form(f"reopen_{case['id']}"):
                    reason = st.text_area("Still unresolved? Explain what remains", key=f"reopen_reason_{case['id']}")
                    reopen = st.form_submit_button("Request reopening")
                if reopen:
                    try:
                        update_complaint(actor, case["id"], "Reopened", remarks=reason)
                        st.success("Your report has been reopened for review."); st.rerun()
                    except Exception as exc: st.error(str(exc))
    with alerts_tab:
        st.subheader("Neighbourhood signals")
        hotspots = get_public_hotspots(area=actor.get("area") if actor.get("area") and actor.get("area") != "Unassigned" else None)
        if hotspots:
            st.dataframe(pd.DataFrame(hotspots), use_container_width=True, hide_index=True)
            st.warning("These are aggregate complaint clusters for investigation, not confirmed disease outbreaks. Follow only authorised public-health advisories.")
        else:
            st.info("No complaint cluster meets the minimum threshold of three reports in your visible locality. This does not guarantee that an area is risk-free.")
        urgent = [c for c in cases if c["critical_override"] or c["status"] == "Escalated"]
        if urgent:
            st.markdown("**Your urgent case notices**")
            for c in urgent[:5]: st.warning(f"Case {c['id'][:8]}: a high-priority civic safety report is being reviewed. Follow official advisories for health guidance.")


def field_officer_dashboard(actor: dict):
    hero(f"Welcome, {actor['full_name']}", f"Field operations · Jurisdiction: {actor.get('area', 'Unassigned')}", "FIELD OFFICER CONSOLE")
    cases = list_complaints(actor)
    summary = dashboard_summary(actor)
    show_metrics(summary, ("total", "open", "escalated", "resolved"))
    queue_tab, update_tab, map_tab = st.tabs(["Assignment queue", "Update a case", "Location view"])
    with queue_tab:
        st.subheader("Reports in your jurisdiction")
        if cases:
            st.dataframe(safe_df(cases, ["id", "category", "area", "location", "severity", "risk_level", "priority_score", "status", "assigned_officer_name", "representative_name", "created_at"]), use_container_width=True, hide_index=True)
            st.caption("Critical and overdue cases should be actioned first. Assignment remains visible in the Admin audit trail.")
            csv_download(cases, "field_officer_cases.csv", "Download my work queue")
        else: st.info("No reports have been routed to your jurisdiction yet.")
    with update_tab:
        if not cases:
            st.info("There are no in-scope cases to update.")
        else:
            opts = {case_label(c): c for c in cases}
            selected = st.selectbox("Select a case", list(opts), key="officer_case_select")
            case = opts[selected]
            st.markdown(f"**{case['category']} · {case['risk_level']} risk · Priority {case['priority_score']}/100**")
            st.write(case["description"])
            show_evidence(actor, case["id"])
            with st.form(f"officer_update_{case['id']}"):
                choices = ["Under Review", "Assigned", "In Progress", "Escalated", "Resolved"]
                status_value = st.selectbox("Update status", choices, index=choices.index(case["status"]) if case["status"] in choices else 0)
                remarks = st.text_area("Field remarks", value=case.get("officer_remarks", ""), help="Record what you saw, who owns the next step, and any blocker.")
                action = st.text_area("Action taken / resolution details", value=case.get("action_taken", ""), help="Required to mark a case Resolved.")
                evidence = st.file_uploader("Attach inspection or after-work evidence", type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "mp3", "wav", "m4a"], key=f"officer_file_{case['id']}")
                submit = st.form_submit_button("Save field update", type="primary")
            if submit:
                if evidence is not None and evidence.size > MAX_UPLOAD_MB * 1024 * 1024:
                    st.error(f"File exceeds {MAX_UPLOAD_MB} MB limit.")
                else:
                    ftuple = (evidence.name, evidence.type or "application/octet-stream", evidence.getvalue()) if evidence else None
                    try:
                        update_complaint(actor, case["id"], status_value, remarks, action)
                        if ftuple: add_evidence(actor, case["id"], ftuple, "Field inspection / resolution evidence")
                        st.success("Case update saved and audit event recorded."); st.rerun()
                    except Exception as exc: st.error(str(exc))
    with map_tab:
        show_map(cases, "Cases in your jurisdiction")


def admin_dashboard(actor: dict):
    hero("System control centre", "Manage people, route cases, investigate hotspots, and audit service outcomes.", "ADMIN OPERATIONS")
    cases = list_complaints(actor, limit=2000)
    summary = dashboard_summary(actor)
    show_metrics(summary, ("total", "open", "critical", "review_required", "escalated", "resolved"))
    overview_tab, cases_tab, users_tab, analytics_tab, audit_tab = st.tabs(["Overview", "Case management", "User & role management", "Hotspot analytics", "Audit & exports"])
    with overview_tab:
        left, right = st.columns(2)
        with left:
            st.subheader("Status distribution")
            counts = pd.DataFrame([{"Status": k, "Reports": v} for k, v in summary["statuses"].items() if v])
            if len(counts): st.plotly_chart(px.pie(counts, names="Status", values="Reports", hole=.55), use_container_width=True)
            else: st.info("Status analytics will appear after reports are submitted.")
        with right:
            st.subheader("Priority watchlist")
            watch = [c for c in cases if c["priority_score"] >= 80 or c["review_required"]]
            if watch: st.dataframe(safe_df(watch[:12], ["id", "category", "area", "severity", "status", "priority_score", "ai_validation"]), use_container_width=True, hide_index=True)
            else: st.success("No urgent or review-flagged reports currently in the queue.")
        show_map(cases, "System issue map")
    with cases_tab:
        st.subheader("Review, assign, and escalate")
        all_areas = sorted({c["area"] for c in cases})
        f1, f2 = st.columns(2)
        area_filter = f1.selectbox("Filter by locality", ["All areas"] + all_areas, key="admin_area_filter")
        status_filter = f2.selectbox("Filter by status", ["All statuses"] + sorted(STATUSES), key="admin_status_filter")
        filtered = [c for c in cases if (area_filter == "All areas" or c["area"] == area_filter) and (status_filter == "All statuses" or c["status"] == status_filter)]
        st.dataframe(safe_df(filtered, ["id", "citizen_name", "category", "area", "location", "severity", "risk_level", "priority_score", "status", "assigned_officer_name", "representative_name", "ai_validation", "triage_provider", "created_at"]), use_container_width=True, hide_index=True)
        if filtered:
            opts = {case_label(c): c for c in filtered}
            selected = st.selectbox("Select report for action", list(opts), key="admin_case_select")
            case = opts[selected]
            st.markdown(f"**{case['category']} · {case['area']} · {case['status']}**")
            st.write(case["description"])
            with st.expander("Triage reasoning and existing evidence"):
                st.write(case["ai_reason"])
                st.caption(f"Assessment: {case['ai_validation']} · Confidence: {case['ai_confidence']}% · Provider: {case['triage_provider']} · Review required: {case['review_required']}")
                show_evidence(actor, case["id"])
            try:
                users = list_users(actor)
                officers = [u for u in users if u["role"] == "Field Officer" and u["active"]]
                reps = [u for u in users if u["role"] == "Representative" and u["active"]]
            except Exception: officers, reps = [], []
            with st.form(f"assign_{case['id']}"):
                officer_labels = {"Unassigned": None} | {f"{u['full_name']} · {u['area']} (ID {u['id']})": u["id"] for u in officers}
                rep_labels = {"Keep current representative": case.get("representative_id")} | {f"{u['full_name']} · {u['area']} (ID {u['id']})": u["id"] for u in reps}
                olabs = list(officer_labels); rlabs = list(rep_labels)
                officer_index = next((i for i, label in enumerate(olabs) if officer_labels[label] == case.get("assigned_officer_id")), 0)
                rep_index = next((i for i, label in enumerate(rlabs) if rep_labels[label] == case.get("representative_id")), 0)
                oc = st.selectbox("Assign Field Officer", olabs, index=officer_index)
                rc = st.selectbox("Forward / attach Representative", rlabs, index=rep_index)
                assign = st.form_submit_button("Save assignments", type="primary")
            if assign:
                try:
                    assign_complaint(actor, case["id"], officer_labels[oc], rep_labels[rc])
                    st.success("Assignment saved."); st.rerun()
                except Exception as exc: st.error(str(exc))
            with st.form(f"admin_status_{case['id']}"):
                status_choices = sorted(STATUSES)
                new_status = st.selectbox("Administrative status override", status_choices, index=status_choices.index(case["status"]) if case["status"] in status_choices else 0)
                admin_remarks = st.text_area("Admin review notes", value=case.get("officer_remarks", ""))
                admin_action = st.text_area("Action taken / resolution evidence notes", value=case.get("action_taken", ""))
                save_status = st.form_submit_button("Save status and notes")
            if save_status:
                try:
                    update_complaint(actor, case["id"], new_status, admin_remarks, admin_action)
                    st.success("Status update saved."); st.rerun()
                except Exception as exc: st.error(str(exc))
        csv_download(cases, "swasthyagrid_all_reports.csv", "Download all reports as CSV")
    with users_tab:
        st.subheader("Create an account")
        with st.form("create_user_form", clear_on_submit=True):
            u1, u2 = st.columns(2)
            username = u1.text_input("User ID", placeholder="e.g. officer_ward12")
            full_name = u2.text_input("Full name")
            u3, u4 = st.columns(2)
            role = u3.selectbox("Role", sorted(ROLES, key=lambda r: ["Admin", "Representative", "Field Officer", "Citizen"].index(r)))
            area = u4.text_input("Assigned ward / area", value="Unassigned")
            password = st.text_input("Temporary password (10+ characters)", type="password")
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            try:
                user = create_user(actor, username, full_name, password, role, area)
                st.success(f"Created {user['role']} account: {user['username']}.")
            except Exception as exc: st.error(str(exc))
        st.subheader("Existing accounts")
        try:
            users = list_users(actor)
            st.dataframe(safe_df(users, ["id", "username", "full_name", "role", "area", "active", "created_at"]), use_container_width=True, hide_index=True)
            if users:
                user_options = {f"{u['username']} · {u['role']} · {u['area']} (ID {u['id']})": u for u in users}
                chosen_user = st.selectbox("Manage an account", list(user_options), key="managed_user_choice")
                target_user = user_options[chosen_user]
                with st.form(f"manage_user_{target_user['id']}"):
                    active_flag = st.checkbox("Account active", value=bool(target_user["active"]))
                    changed_area = st.text_input("Update ward / area", value=target_user["area"])
                    reset_password = st.text_input("New password (leave blank to keep current; 10+ characters)", type="password")
                    manage_submit = st.form_submit_button("Save account changes")
                if manage_submit:
                    try:
                        update_user_admin(actor, target_user["id"], active=active_flag, new_password=reset_password or None, area=changed_area)
                        st.success("Account changes saved and audited."); st.rerun()
                    except Exception as exc: st.error(str(exc))
        except Exception as exc: st.error(str(exc))
    with analytics_tab:
        st.subheader("CivicPulse · ward-level signals")
        if cases:
            df = pd.DataFrame(cases)
            category_counts = df.groupby("category", as_index=False).size().rename(columns={"size": "Reports"})
            area_counts = df.groupby("area", as_index=False).agg(Reports=("id", "count"), HighPriority=("priority_score", lambda s: int((s >= 80).sum())))
            c1, c2 = st.columns(2)
            with c1: st.plotly_chart(px.bar(category_counts, x="category", y="Reports", title="Reports by category", text_auto=True), use_container_width=True)
            with c2: st.plotly_chart(px.bar(area_counts, x="area", y="HighPriority", title="High-priority reports by area", text_auto=True), use_container_width=True)
            st.markdown("**Potential clusters (3+ reports in the same area/category)**")
            clusters = df.groupby(["area", "category"], as_index=False).size().rename(columns={"size": "Reports"})
            clusters = clusters[clusters["Reports"] >= 3].sort_values("Reports", ascending=False)
            if len(clusters): st.dataframe(clusters, use_container_width=True, hide_index=True)
            else: st.info("No clusters meet the configured count threshold yet. Low-count groups are not presented as public hotspots.")
        else: st.info("Analytics will be available when reports arrive.")
        st.caption("CivicPulse signals are investigatory leads, not confirmation of disease outbreaks or fault. Confirm with authorised field/health teams before issuing public advisories.")
    with audit_tab:
        st.subheader("Audit ledger")
        try:
            logs = list_audit_logs(actor)
            st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True) if logs else st.info("No events yet.")
            st.download_button("Download audit ledger", pd.DataFrame(logs).to_csv(index=False).encode("utf-8-sig"), "swasthyagrid_audit.csv", "text/csv")
        except Exception as exc: st.error(str(exc))


def representative_dashboard(actor: dict):
    hero(f"Welcome, {actor['full_name']}", f"Constituency and ward oversight · {actor.get('area', 'Unassigned')}", "REPRESENTATIVE OFFICE")
    cases = list_complaints(actor)
    summary = dashboard_summary(actor)
    show_metrics(summary, ("total", "open", "escalated", "resolved"))
    tab1, tab2, tab3 = st.tabs(["Oversight overview", "Reports & follow-up", "Download reports"])
    with tab1:
        left, right = st.columns(2)
        with left:
            st.subheader("Case status")
            counts = pd.DataFrame([{"Status": k, "Reports": v} for k, v in summary["statuses"].items() if v])
            if len(counts): st.plotly_chart(px.pie(counts, names="Status", values="Reports", hole=.52), use_container_width=True)
            else: st.info("No reports in this oversight scope.")
        with right:
            st.subheader("Area/category signals")
            if cases:
                df = pd.DataFrame(cases)
                clusters = df.groupby(["area", "category"], as_index=False).size().rename(columns={"size": "Reports"})
                clusters = clusters[clusters["Reports"] >= 3]
                if len(clusters): st.dataframe(clusters, use_container_width=True, hide_index=True)
                else: st.info("No cluster meets the display threshold. Small groups are suppressed for privacy.")
        show_map(cases, "Oversight map")
    with tab2:
        st.subheader("Monitor unresolved matters")
        display = safe_df(cases, ["id", "category", "area", "location", "severity", "risk_level", "priority_score", "status", "created_at", "updated_at"])
        if len(display):
            display["id"] = display["id"].str.slice(0, 8)
            st.dataframe(display, use_container_width=True, hide_index=True)
        else: st.info("No reports available.")
        unresolved = [c for c in cases if c["status"] not in {"Resolved", "Rejected"}]
        if unresolved:
            opts = {case_label(c): c for c in unresolved}
            label = st.selectbox("Request action / escalation", list(opts), key="rep_case_select")
            case = opts[label]
            st.write(case["description"])
            remarks = st.text_area("Guidance to Admin / assigned officer", key=f"rep_note_{case['id']}", placeholder="Explain what needs attention and why.")
            if st.button("Forward for Admin action", type="primary", key=f"rep_forward_{case['id']}"):
                try:
                    update_complaint(actor, case["id"], "Escalated", remarks=remarks)
                    st.success("Matter escalated. It is recorded in the audit ledger."); st.rerun()
                except Exception as exc: st.error(str(exc))
    with tab3:
        st.subheader("Download oversight reports")
        export = [{k: v for k, v in c.items() if k not in {"citizen_id", "citizen_name"}} for c in cases]
        st.caption("Citizen identities are excluded from representative exports. Very small geographic clusters are not highlighted as public hotspots.")
        csv_download(export, "constituency_oversight_report.csv", "Download oversight report")
        if cases:
            unresolved = [c for c in export if c["status"] not in {"Resolved", "Rejected"}]
            csv_download(unresolved, "constituency_open_matters.csv", "Download open matters only")


def main():
    actor = st.session_state.get("sg_user")
    if actor:
        fresh_actor = get_active_user(actor.get("id"), actor.get("_token_version"))
        if fresh_actor is None:
            st.session_state.pop("sg_user", None)
            st.error("This account is inactive. Please contact the administrator.")
            login_screen()
            return
        actor = fresh_actor
        st.session_state["sg_user"] = actor
    if not actor:
        login_screen()
        return
    with st.sidebar:
        st.markdown("# 🌐 SwasthyaGrid")
        st.caption("Civic Intelligence & Health-Risk Triage")
        st.divider()
        st.markdown(f"**{actor['full_name']}**")
        st.caption(f"{actor['role']} · {actor.get('area', 'Unassigned')}")
        if ALLOW_DEMO_LOGIN:
            st.warning("DEMO MODE · fictional sample data")
        if APP_ENV == "production" and not DATABASE_URL_SETTING:
            st.error("Production is using local SQLite. Configure DATABASE_URL to a managed PostgreSQL database for durable cloud storage.")
        if GEMINI_API_KEY: st.caption("AI provider: Gemini configured")
        elif GROQ_API_KEY: st.caption("AI provider: Groq configured")
        else: st.caption("AI provider: rule-based fallback")
        st.divider()
        if st.button("Sign out", use_container_width=True): logout()
        st.markdown("---")
        st.caption("Built for human-reviewed, privacy-aware public-service operations.")
    role = actor["role"]
    if role == "Citizen": citizen_dashboard(actor)
    elif role == "Field Officer": field_officer_dashboard(actor)
    elif role == "Admin": admin_dashboard(actor)
    elif role == "Representative": representative_dashboard(actor)
    else:
        st.error("Your account has an unsupported role. Contact the administrator.")
        if st.button("Sign out"): logout()

main()
