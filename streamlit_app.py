"""Smart Campus Attendance Management System – Streamlit web app (presentation layer).

Run locally:   streamlit run streamlit_app.py
Data is stored in Firebase Firestore when [firebase] credentials are in
.streamlit/secrets.toml (or in the Streamlit Cloud "Secrets" settings).
Without them the app runs in demo mode and keeps data in memory only.
"""
import base64
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from scams.models import ATTENDANCE_STATUSES, ROLES
from scams.seed import ADMINISTRATORS, INSTRUCTORS, seed
from scams.services import (AdministrationService, AttendanceService, AuthenticationService,
                            ReportingService, ServiceError, all_courses, all_users, course_enrollments,
                            course_sessions, get_course, get_policy, get_user, record_corrections,
                            session_records)
from scams.store import FirestoreStore, MemoryStore

st.set_page_config(page_title="Smart Campus Attendance", page_icon="✅", layout="wide")
ASSETS = Path(__file__).parent / "assets"


# ------------------------------------------------------------------ data store
def _firebase_secrets():
    try:
        return dict(st.secrets["firebase"]) if "firebase" in st.secrets else None
    except Exception:  # no secrets file at all
        return None


@st.cache_resource(show_spinner="Connecting to the database…")
def get_store():
    info = _firebase_secrets()
    store = FirestoreStore.from_service_account(info) if info else MemoryStore()
    seed(store)
    return store, ("Firestore" if info else "Demo (in memory)")


S, MODE = get_store()


# ------------------------------------------------------------------ helpers
def flash(text, kind="success"):
    st.session_state.setdefault("flash", []).append((kind, text))


def show_flash():
    for kind, text in st.session_state.pop("flash", []):
        getattr(st, kind)(text)


def run(action, success=None):
    """Run a service call; show its error or a success message, then refresh the page."""
    try:
        result = action()
    except ServiceError as e:
        flash(str(e), "error")
    else:
        if success:
            flash(success(result) if callable(success) else success)
    st.rerun()


def table(rows, columns):
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True, width="stretch")
    else:
        st.info("Nothing to show yet.")


def ud_footer():
    logo = base64.b64encode((ASSETS / "ud_logo.png").read_bytes()).decode()
    st.markdown(
        f"""<div style="margin-top:48px;padding:28px 0 8px;text-align:center;
             background:linear-gradient(180deg,rgba(255,255,255,0),#e9f0ed);border-radius:12px">
          <img src="data:image/png;base64,{logo}" style="height:130px;opacity:.22" alt="">
          <div style="color:#6b7785;font-size:13px;margin-top:10px">EECE 324 student project · University of Dubai ·
          Smart Campus Attendance Management System (demo, not an official university system)</div></div>""",
        unsafe_allow_html=True)


def current_user():
    user = get_user(S, st.session_state.get("uid"))
    if user is None or not user.active:
        st.session_state.pop("uid", None)
        return None
    return user


def fill_login(email, password):
    st.session_state["login_email"], st.session_state["login_password"] = email, password


# ================================================================== home + UC01
def home_page():
    show_flash()
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.title("Smart Campus Attendance Management System")
        st.write("One place to record, correct and report student attendance, replacing paper sheets and "
                 "spreadsheets. Every record is tied to a course section, a class session and a student, "
                 "and every correction is logged.")
        st.subheader("Who uses it")
        with st.container(border=True):
            st.markdown("**Administrator**\n- Creates student, instructor and administrator accounts\n"
                        "- Creates courses and assigns instructors\n- Enrolls and drops students\n"
                        "- Sets the attendance threshold and sees low-attendance alerts")
        with st.container(border=True):
            st.markdown("**Instructor**\n- Creates class sessions for assigned courses\n"
                        "- Opens, closes and finalizes sessions\n"
                        "- Records attendance as one batch and corrects mistakes\n"
                        "- Generates attendance reports with percentages")
        with st.container(border=True):
            st.markdown("**Student**\n- Views attendance history by semester and course\n"
                        "- Sees their attendance percentage and whether it is below the threshold")
        st.subheader("How it works")
        st.markdown("1. The administrator creates students and courses, then enrolls students.\n"
                    "2. The instructor creates a session and opens it.\n"
                    "3. The instructor records a status for every student: Present, Absent, Late or Excused.\n"
                    "4. The instructor closes and then finalizes the session. Finalized records are locked.\n"
                    "5. Reports count only Present in finalized sessions and flag students below the threshold.")
    with right:
        with st.container(border=True):
            st.subheader("Log in")
            with st.form("login"):
                email = st.text_input("Email", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                if st.form_submit_button("Log in", type="primary", width="stretch"):
                    try:
                        user = AuthenticationService.authenticate(S, email, password)
                        st.session_state["uid"] = user.id
                        st.rerun()
                    except ServiceError as e:
                        st.error(str(e))
        with st.container(border=True):
            st.subheader("Demo accounts")
            st.caption("Click an account to fill in the login form.")
            accounts = ([("Administrator", a) for a in ADMINISTRATORS] +
                        [("Instructor", i) for i in INSTRUCTORS])
            for role, a in accounts:
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{role}** · {a['full_name']}  \n`{a['email']}` · password `{a['password']}`")
                c2.button("Use", key=f"use_{a['email']}", on_click=fill_login, args=(a["email"], a["password"]))
            st.caption("Students log in with the email and password the administrator sets for them.")
        if MODE.startswith("Demo"):
            st.info("Demo mode: Firebase is not connected, so data is kept in memory and is lost when the app "
                    "restarts. Add your Firebase key to the app's secrets to store data in Firestore.")
    ud_footer()


# ================================================================== Administrator
def admin_dashboard(user):
    users = all_users(S)
    c = st.columns(5)
    c[0].metric("Students", sum(u.role == "Student" for u in users))
    c[1].metric("Instructors", sum(u.role == "Instructor" for u in users))
    c[2].metric("Courses", len(all_courses(S)))
    c[3].metric("Threshold", f"{get_policy(S).threshold:g}%")
    c[4].metric("Low-attendance alerts", len(ReportingService.low_attendance_alerts(S)))
    st.caption("Use the menu on the left to manage users, courses, enrollments and the threshold.")


def admin_users(user):  # UC02
    tab_list, tab_new, tab_edit = st.tabs(["All accounts", "Create account", "Edit / deactivate"])
    with tab_list:
        role = st.selectbox("Show", ["All"] + ROLES)
        users = all_users(S, None if role == "All" else role)
        table([(u.full_name, u.email, u.role, u.number, "Active" if u.active else "Inactive") for u in users],
              ["Name", "Email", "Role", "ID number", "Status"])
    with tab_new:
        with st.form("new_user", clear_on_submit=True):
            c1, c2 = st.columns(2)
            role = c1.selectbox("Role", ROLES)
            name = c2.text_input("Full name")
            email = c1.text_input("Email")
            number = c2.text_input("Student ID / employee number")
            pw = c1.text_input("Password (min. 6 characters)", type="password")
            if st.form_submit_button("Create account", type="primary"):
                run(lambda: AdministrationService.create_user(S, role, name, email, pw, number),
                    lambda u: f"{u.role} account created for {u.full_name}.")
    with tab_edit:
        users = all_users(S)
        pick = st.selectbox("Account", users, format_func=lambda u: f"{u.full_name} ({u.role}, {u.email})")
        if pick:
            with st.form(f"edit_{pick.id}"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Full name", pick.full_name)
                email = c2.text_input("Email", pick.email)
                number = c1.text_input("ID number", pick.number)
                pw = c2.text_input("New password (leave blank to keep)", type="password")
                if st.form_submit_button("Save changes", type="primary"):
                    run(lambda: AdministrationService.update_user(S, pick.id, name, email, number, pw),
                        f"Account for {name} updated.")
            if pick.id != user.id:
                label = "Deactivate account" if pick.active else "Activate account"
                if st.button(label):
                    run(lambda: AdministrationService.set_active(S, user, pick.id, not pick.active),
                        lambda u: f"{u.full_name} is now {'active' if u.active else 'deactivated'}.")


def _instructor_choice(label, current=None, key=None):
    instructors = [u for u in all_users(S, "Instructor") if u.active]
    options = ["— Not assigned —"] + [f"{u.full_name} <{u.email}>" for u in instructors]
    ids = [None] + [u.id for u in instructors]
    idx = ids.index(current) if current in ids else 0
    return ids[options.index(st.selectbox(label, options, index=idx, key=key))]


def admin_courses(user):  # UC03
    courses = all_courses(S)
    tab_list, tab_new, tab_edit = st.tabs(["All courses", "Create course", "Edit course"])
    names = {u.id: u.full_name for u in all_users(S, "Instructor")}
    with tab_list:
        table([(c.course_code, c.course_name, c.semester, c.section, names.get(c.instructor_id, "—"),
                sum(e.withdrawn_on is None for e in course_enrollments(S, c.id))) for c in courses],
              ["Code", "Name", "Semester", "Section", "Instructor", "Enrolled"])
    with tab_new:
        with st.form("new_course", clear_on_submit=True):
            c1, c2 = st.columns(2)
            code = c1.text_input("Course code", placeholder="EECE324")
            name = c2.text_input("Course name", placeholder="Software Engineering")
            sem = c1.text_input("Semester", placeholder="Fall 2026")
            sec = c2.text_input("Section", "1")
            instr = _instructor_choice("Instructor", key="new_course_instr")
            if st.form_submit_button("Create course", type="primary"):
                run(lambda: AdministrationService.save_course(S, code, name, sem, sec, instr),
                    lambda c: f"Course {c.course_code} created.")
    with tab_edit:
        if not courses:
            st.info("No courses yet.")
        else:
            c = st.selectbox("Course", courses, format_func=lambda c: c.label)
            with st.form(f"edit_course_{c.id}"):
                c1, c2 = st.columns(2)
                code = c1.text_input("Course code", c.course_code)
                name = c2.text_input("Course name", c.course_name)
                sem = c1.text_input("Semester", c.semester)
                sec = c2.text_input("Section", c.section)
                instr = _instructor_choice("Instructor", c.instructor_id, key=f"instr_{c.id}")
                if st.form_submit_button("Save changes", type="primary"):
                    run(lambda: AdministrationService.save_course(S, code, name, sem, sec, instr, c.id),
                        lambda c: f"Course {c.course_code} updated.")


def admin_enrollments(user):  # UC04
    courses = all_courses(S)
    if not courses:
        st.info("Create a course first.")
        return
    course = st.selectbox("Course", courses, format_func=lambda c: c.label)
    enrollments = course_enrollments(S, course.id)
    students = {u.id: u for u in all_users(S, "Student")}
    current = {e.student_id for e in enrollments if e.withdrawn_on is None}
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**Enroll a student**")
        available = [u for u in students.values() if u.active and u.id not in current]
        if available:
            with st.form("enroll", clear_on_submit=True):
                who = st.selectbox("Student", available, format_func=lambda u: f"{u.full_name} ({u.student_number})")
                when = st.date_input("Enrollment date", date.today())
                if st.form_submit_button("Enroll", type="primary"):
                    run(lambda: AdministrationService.enroll(S, course.id, who.id, when), f"{who.full_name} enrolled.")
        else:
            st.caption("No more students to enroll. Create student accounts under Users.")
    with c2, st.container(border=True):
        st.markdown("**Drop a student**")
        active = [e for e in enrollments if e.withdrawn_on is None and e.student_id in students]
        if active:
            with st.form("drop"):
                e = st.selectbox("Student", active, format_func=lambda e: students[e.student_id].full_name)
                when = st.date_input("Drop date", date.today())
                if st.form_submit_button("Drop"):
                    run(lambda: AdministrationService.drop(S, e.id, when),
                        f"{students[e.student_id].full_name} dropped from the course.")
        else:
            st.caption("No active enrollments.")
    st.markdown("**Enrollments**")
    table([(students[e.student_id].full_name, students[e.student_id].student_number, e.enrolled_on,
            e.withdrawn_on or "—") for e in sorted(enrollments, key=lambda e: students[e.student_id].full_name)
           if e.student_id in students], ["Student", "Student ID", "Enrolled on", "Dropped on"])


def admin_threshold(user):  # UC10
    st.metric("Current threshold", f"{get_policy(S).threshold:g}%")
    with st.form("threshold"):
        value = st.text_input("New threshold (0–100)", f"{get_policy(S).threshold:g}")
        if st.form_submit_button("Save", type="primary"):
            run(lambda: AdministrationService.update_threshold(S, value),
                lambda p: f"Attendance threshold updated to {p.threshold:g}%.")


def admin_alerts(user):  # FR12
    st.caption(f"Students below the {get_policy(S).threshold:g}% threshold, based on finalized sessions only.")
    table([(c.label, r.student.full_name, r.student.student_number, f"{r.present} / {r.eligible}",
            f"{r.percentage}%") for c, r in ReportingService.low_attendance_alerts(S)],
          ["Course", "Student", "Student ID", "Present / eligible", "Attendance"])


# ================================================================== Instructor
STATE_ACTIONS = {"Scheduled": [("open", "Open session")], "Open": [("close", "Close session")],
                 "Closed": [("reopen", "Reopen session"), ("finalize", "Finalize session")], "Finalized": []}


def instructor_sessions(user):  # UC05, UC06, UC07
    courses = AttendanceService.courses_for(S, user)
    if not courses:
        st.info("No courses are assigned to you yet. The administrator assigns courses.")
        return
    course = st.selectbox("Course", courses, format_func=lambda c: c.label)
    with st.expander("➕ Create attendance session"):
        with st.form("new_session", clear_on_submit=True):
            c1, c2 = st.columns([1, 2])
            day = c1.date_input("Session date", date.today())
            details = c2.text_input("Details (optional)", placeholder="e.g. Lecture 12 – Design class diagrams")
            if st.form_submit_button("Create session", type="primary"):
                run(lambda: AttendanceService.create_session(S, user, course.id, day, details),
                    lambda x: f"Session for {x.session_date} created in Scheduled state.")
    sessions = course_sessions(S, course.id)
    if not sessions:
        st.info("No sessions yet. Create the first one above.")
        return
    table([(x.session_date, x.details or "—", x.state, len(session_records(S, x.id))) for x in sessions],
          ["Date", "Details", "State", "Records"])
    st.caption("Session life cycle: Scheduled → Open → Closed → Finalized. A closed session can be reopened; "
               "a finalized session is locked.")

    session = st.selectbox("Work on session", sessions, index=len(sessions) - 1,
                           format_func=lambda x: f"{x.session_date} – {x.state}")
    st.subheader(f"Session {session.session_date} · {session.state}")
    cols = st.columns(4)
    for i, (action, label) in enumerate(STATE_ACTIONS[session.state]):
        if cols[i].button(label, key=f"{action}_{session.id}", type="primary" if action != "finalize" else "secondary"):
            run(lambda a=action: AttendanceService.change_state(S, user, session.id, a),
                lambda x: f"Session {x.session_date} is now {x.state}.")

    records = session_records(S, session.id)
    have = {r.student_id for r in records}
    pending = [u for u in AttendanceService.eligible_students(S, session) if u.id not in have]

    if pending:  # UC06
        with st.container(border=True):
            st.markdown("**Record attendance**")
            if session.is_open():
                st.caption("Choose a status for every student. The batch is saved only if every entry is valid.")
                with st.form(f"record_{session.id}"):
                    entries = {}
                    for u in pending:
                        entries[u.id] = st.radio(f"{u.full_name} ({u.student_number})", ATTENDANCE_STATUSES,
                                                 index=None, horizontal=True, key=f"st_{session.id}_{u.id}")
                    if st.form_submit_button("Submit attendance batch", type="primary"):
                        run(lambda: AttendanceService.record_attendance(
                                S, user, session.id, {k: v for k, v in entries.items() if v} or {}),
                            lambda n: f"Attendance saved for {n} student(s).")
            else:
                st.warning(f"This session is {session.state}. Attendance can only be recorded while it is Open "
                           f"({len(pending)} student(s) still without a record).")

    if records:  # UC07
        names = {u.id: u for u in all_users(S, "Student")}
        st.markdown("**Recorded attendance**")
        table([(names[r.student_id].full_name if r.student_id in names else r.student_id, r.status, r.updated_at,
                "; ".join(f"{c.previous_status} → {c.new_status} by {(get_user(S, c.corrected_by) or names.get(c.corrected_by)).full_name} on {c.corrected_at}"
                          for c in record_corrections(S, r.id)) or "—")
               for r in sorted(records, key=lambda r: names[r.student_id].full_name if r.student_id in names else "")],
              ["Student", "Status", "Last updated", "Corrections"])
        if session.state in ("Open", "Closed"):
            with st.form(f"correct_{session.id}"):
                st.markdown("**Correct a record**")
                c1, c2 = st.columns(2)
                rec = c1.selectbox("Student", records, format_func=lambda r: f"{names[r.student_id].full_name} ({r.status})")
                new = c2.selectbox("New status", ATTENDANCE_STATUSES)
                if st.form_submit_button("Save correction"):
                    run(lambda: AttendanceService.correct_attendance(S, user, rec.id, new),
                        lambda r: f"Record corrected to {r.status}. The change was logged.")
        elif session.is_finalized():
            st.caption("This session is finalized, so its records are locked.")


def instructor_report(user):  # UC09
    courses = AttendanceService.courses_for(S, user)
    if not courses:
        st.info("No courses are assigned to you yet.")
        return
    course = st.selectbox("Course", courses, format_func=lambda c: c.label)
    days = [x.day for x in course_sessions(S, course.id)]
    c1, c2 = st.columns(2)
    start = c1.date_input("From", min(days) if days else date.today())
    end = c2.date_input("To", max(days) if days else date.today())
    if st.button("Generate report", type="primary"):
        try:
            rep = ReportingService.generate_report(S, user, course.id, start, end)
        except ServiceError as e:
            st.error(str(e))
            return
        st.write(f"Threshold **{rep.threshold:g}%** · finalized sessions in period **{rep.finalized_sessions}**")
        if rep.finalized_sessions == 0:
            st.info("There are no finalized sessions in this period, so no percentages can be calculated yet.")
        table([(r.student.full_name, r.student.student_number, r.present, r.eligible,
                "N/A" if r.percentage is None else f"{r.percentage}%",
                "N/A" if r.percentage is None else ("Yes" if r.below_threshold else "No")) for r in rep.entries],
              ["Student", "Student ID", "Present", "Eligible sessions", "Attendance", "Below threshold"])
        st.caption("Only Present counts as attended. Students with no eligible finalized sessions show N/A.")


# ================================================================== Student
def student_history(user):  # UC08
    courses = ReportingService.student_courses(S, user)
    if not courses:
        st.info("You are not enrolled in any course yet.")
        return
    semesters = sorted({c.semester for c in courses})
    c1, c2 = st.columns([1, 2])
    sem = c1.selectbox("Semester", semesters, index=len(semesters) - 1)
    course = c2.selectbox("Course / section", [c for c in courses if c.semester == sem],
                          format_func=lambda c: f"{c.course_code} – {c.course_name} (Sec {c.section})")
    try:
        course, rows, pct, threshold = ReportingService.attendance_history(S, user, course.id)
    except ServiceError as e:
        st.error(str(e))
        return
    st.metric("Attendance (finalized sessions)", "N/A" if pct is None else f"{pct}%",
              help=f"Threshold {threshold:g}%")
    if pct is not None and pct < threshold:
        st.error("Your attendance is below the required threshold.")
    table([(x.session_date, x.state, r.status if r else "Not recorded") for x, r in rows],
          ["Session date", "Session state", "My status"])


# ================================================================== layout
PAGES = {
    "Administrator": {"Dashboard": admin_dashboard, "Users": admin_users, "Courses": admin_courses,
                      "Enrollments": admin_enrollments, "Threshold": admin_threshold, "Alerts": admin_alerts},
    "Instructor": {"Sessions & attendance": instructor_sessions, "Attendance report": instructor_report},
    "Student": {"My attendance": student_history},
}


def main():
    user = current_user()
    if user is None:
        home_page()
        return
    with st.sidebar:
        st.markdown(f"### Smart Campus Attendance\n**{user.full_name}**  \n{user.role}")
        page = st.radio("Menu", list(PAGES[user.role]), label_visibility="collapsed")
        if st.button("Log out", width="stretch"):
            st.session_state.clear()
            st.rerun()
        st.caption(f"Database: {MODE}")
    st.header(page)
    show_flash()
    PAGES[user.role][page](user)
    ud_footer()


main()
