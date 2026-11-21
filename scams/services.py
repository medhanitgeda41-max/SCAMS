"""Application layer: controller classes from the design class diagram.

AuthenticationService (UC01), AdministrationService (UC02–UC04, UC10),
AttendanceService (UC05–UC07) and ReportingService (UC08, UC09, FR12).
Every business rule lives here or in the entity classes, never in the pages.
"""
from __future__ import annotations

from datetime import date, datetime

from .models import (ATTENDANCE_STATUSES, ROLES, AttendanceCorrectionLog, AttendancePolicy,
                     AttendanceRecord, AttendanceReport, ClassSession, Course, Enrollment,
                     ReportRow, User)
from .security import hash_password, verify_password
from .store import DuplicateError, Store


class ServiceError(Exception):
    """A business rule rejected the request. The message is shown to the user."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _iso(value, name: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ServiceError(f"{name} must be a valid date.")


# ------------------------------------------------------------------ lookups
def get_user(s: Store, user_id: str | None) -> User | None:
    doc = s.get("users", user_id) if user_id else None
    return User.from_doc(doc) if doc else None


def all_users(s: Store, role: str | None = None) -> list[User]:
    docs = s.list("users", role=role) if role else s.list("users")
    return sorted((User.from_doc(d) for d in docs), key=lambda u: (u.role, u.full_name))


def get_course(s: Store, course_id: str) -> Course | None:
    doc = s.get("courses", course_id)
    return Course.from_doc(doc) if doc else None


def all_courses(s: Store) -> list[Course]:
    return sorted((Course.from_doc(d) for d in s.list("courses")),
                  key=lambda c: (c.semester, c.course_code, c.section))


def course_enrollments(s: Store, course_id: str) -> list[Enrollment]:
    return [Enrollment.from_doc(d) for d in s.list("enrollments", course_id=course_id)]


def course_sessions(s: Store, course_id: str) -> list[ClassSession]:
    return sorted((ClassSession.from_doc(d) for d in s.list("sessions", course_id=course_id)),
                  key=lambda x: x.session_date)


def session_records(s: Store, session_id: str) -> list[AttendanceRecord]:
    return [AttendanceRecord.from_doc(d) for d in s.list("records", session_id=session_id)]


def record_corrections(s: Store, record_id: str) -> list[AttendanceCorrectionLog]:
    return sorted((AttendanceCorrectionLog.from_doc(d) for d in s.list("corrections", record_id=record_id)),
                  key=lambda c: c.corrected_at)


def get_policy(s: Store) -> AttendancePolicy:
    doc = s.get("settings", "policy") or {"threshold": 75.0, "id": "policy"}
    return AttendancePolicy.from_doc(doc)


# ==================================================================== UC01
class AuthenticationService:
    @staticmethod
    def authenticate(s: Store, email: str, password: str) -> User:
        email = (email or "").strip().lower()
        docs = s.list("users", email=email) if email else []
        user = User.from_doc(docs[0]) if docs else None
        if user is None or not verify_password(password or "", user.password_hash):
            raise ServiceError("Invalid email or password.")
        if not user.is_active():
            raise ServiceError("This account is inactive. Please contact the administrator.")
        return user


# ======================================================= UC02, UC03, UC04, UC10
class AdministrationService:
    @staticmethod
    def create_user(s: Store, role, full_name, email, password, number) -> User:
        full_name, email, number = (full_name or "").strip(), (email or "").strip().lower(), (number or "").strip()
        if role not in ROLES:
            raise ServiceError("Please choose a valid role.")
        if not full_name or not email or not number:
            raise ServiceError("Name, email and ID number are required.")
        if "@" not in email:
            raise ServiceError("Please enter a valid email address.")
        if len(password or "") < 6:
            raise ServiceError("Password must be at least 6 characters.")
        if s.list("users", email=email):
            raise ServiceError("A user with this email already exists.")
        if role == "Student" and s.list("users", student_number=number):
            raise ServiceError("A student with this student ID already exists.")
        user = User(full_name=full_name, email=email, password_hash=hash_password(password), active=True,
                    role=role, student_number=number if role == "Student" else None,
                    employee_number=None if role == "Student" else number)
        user.id = s.add("users", user.to_doc())
        return user

    @staticmethod
    def update_user(s: Store, user_id, full_name, email, number, password="") -> User:
        user = get_user(s, user_id)
        if user is None:
            raise ServiceError("User not found.")
        full_name, email, number = (full_name or "").strip(), (email or "").strip().lower(), (number or "").strip()
        if not full_name or not number or "@" not in email:
            raise ServiceError("Name, a valid email and ID number are required.")
        if any(d["id"] != user_id for d in s.list("users", email=email)):
            raise ServiceError("Another user already uses this email.")
        if user.role == "Student" and any(d["id"] != user_id for d in s.list("users", student_number=number)):
            raise ServiceError("Another student already uses this student ID.")
        changes = {"full_name": full_name, "email": email,
                   ("student_number" if user.role == "Student" else "employee_number"): number}
        if password:
            if len(password) < 6:
                raise ServiceError("Password must be at least 6 characters.")
            changes["password_hash"] = hash_password(password)
        s.update("users", user_id, changes)
        return get_user(s, user_id)

    @staticmethod
    def set_active(s: Store, admin: User, user_id: str, active: bool) -> User:
        user = get_user(s, user_id)
        if user is None:
            raise ServiceError("User not found.")
        if user.id == admin.id and not active:
            raise ServiceError("You cannot deactivate your own account.")
        s.update("users", user_id, {"active": active})
        return get_user(s, user_id)

    # ---------- UC03 Manage Courses
    @staticmethod
    def save_course(s: Store, code, name, semester, section, instructor_id, course_id=None) -> Course:
        code, name, semester, section = [(v or "").strip() for v in (code, name, semester, section)]
        code = code.upper()
        if not all((code, name, semester, section)):
            raise ServiceError("Course code, name, semester and section are required.")
        if instructor_id:
            instr = get_user(s, instructor_id)
            if instr is None or instr.role != "Instructor" or not instr.active:
                raise ServiceError("Please assign an active instructor.")
        clash = [d for d in s.list("courses", course_code=code, semester=semester, section=section)
                 if d["id"] != course_id]
        if clash:
            raise ServiceError("This course section already exists for that semester.")
        course = Course(id=course_id or "", course_code=code, course_name=name, semester=semester,
                        section=section, instructor_id=instructor_id or None)
        if course_id:
            s.set("courses", course_id, course.to_doc())
        else:
            course.id = s.add("courses", course.to_doc())
        return course

    # ---------- UC04 Manage Enrollments
    @staticmethod
    def enroll(s: Store, course_id: str, student_id: str, enrolled_on) -> Enrollment:
        if get_course(s, course_id) is None:
            raise ServiceError("Course not found.")
        student = get_user(s, student_id)
        if student is None or student.role != "Student" or not student.active:
            raise ServiceError("Please select an active student.")
        start = _iso(enrolled_on, "Enrollment date")
        if any(e.student_id == student_id and e.withdrawn_on is None for e in course_enrollments(s, course_id)):
            raise ServiceError(f"{student.full_name} is already enrolled in this course.")
        e = Enrollment(student_id=student_id, course_id=course_id, enrolled_on=start)
        e.id = s.add("enrollments", e.to_doc())
        return e

    @staticmethod
    def drop(s: Store, enrollment_id: str, withdrawn_on) -> Enrollment:
        doc = s.get("enrollments", enrollment_id)
        if doc is None or doc.get("withdrawn_on"):
            raise ServiceError("Active enrollment not found.")
        end = _iso(withdrawn_on, "Drop date")
        if end <= doc["enrolled_on"]:
            raise ServiceError("Drop date must be after the enrollment date.")
        s.update("enrollments", enrollment_id, {"withdrawn_on": end})
        return Enrollment.from_doc({**doc, "withdrawn_on": end})

    # ---------- UC10 Configure Attendance Threshold
    @staticmethod
    def update_threshold(s: Store, value) -> AttendancePolicy:
        try:
            number = float(str(value).strip())
        except ValueError:
            raise ServiceError("Threshold must be a number between 0 and 100. The current threshold was kept.")
        if not 0 <= number <= 100:
            raise ServiceError("Threshold must be between 0 and 100. The current threshold was kept.")
        s.set("settings", "policy", {"threshold": number})
        return AttendancePolicy(id="policy", threshold=number)


# ================================================================= UC05–UC07
class AttendanceService:
    @staticmethod
    def assigned_course(s: Store, instructor: User, course_id: str) -> Course:
        course = get_course(s, course_id)
        if course is None or not course.is_assigned_to(instructor.id):
            raise ServiceError("Access denied: you are not assigned to this course.")
        return course

    @classmethod
    def assigned_session(cls, s: Store, instructor: User, session_id: str) -> ClassSession:
        doc = s.get("sessions", session_id)
        if doc is None:
            raise ServiceError("Session not found.")
        session = ClassSession.from_doc(doc)
        cls.assigned_course(s, instructor, session.course_id)
        return session

    @staticmethod
    def courses_for(s: Store, instructor: User) -> list[Course]:
        return sorted((Course.from_doc(d) for d in s.list("courses", instructor_id=instructor.id)),
                      key=lambda c: (c.semester, c.course_code))

    # ---------- UC05 Create Attendance Session
    @classmethod
    def create_session(cls, s: Store, instructor: User, course_id: str, session_date, details="") -> ClassSession:
        cls.assigned_course(s, instructor, course_id)
        day = _iso(session_date, "Session date")
        if any(x.session_date == day for x in course_sessions(s, course_id)):
            raise ServiceError("A session already exists for this course on that date.")
        session = ClassSession(course_id=course_id, session_date=day, details=(details or "").strip()[:200])
        session.id = s.add("sessions", session.to_doc())
        return session

    @staticmethod
    def eligible_students(s: Store, session: ClassSession) -> list[User]:
        """Students whose enrollment is active on the session date."""
        ids = {e.student_id for e in course_enrollments(s, session.course_id) if e.is_active_on(session.day)}
        users = [get_user(s, i) for i in ids]
        return sorted((u for u in users if u and u.active), key=lambda u: u.full_name)

    # ---------- session state machine (Figure 5.2)
    @classmethod
    def change_state(cls, s: Store, instructor: User, session_id: str, action: str) -> ClassSession:
        session = cls.assigned_session(s, instructor, session_id)
        if action == "finalize":
            have = {r.student_id for r in session_records(s, session_id)}
            missing = [u.full_name for u in cls.eligible_students(s, session) if u.id not in have]
            if missing:
                raise ServiceError("Cannot finalize: attendance is missing for " + ", ".join(missing) + ".")
        moves = {"open": session.open, "close": session.close, "reopen": session.reopen,
                 "finalize": session.finalize_session}
        before = session.state
        if action not in moves or not moves[action]():
            raise ServiceError(f"Cannot {action} a session that is {before}.")
        s.update("sessions", session_id, {"state": session.state})
        return session

    # ---------- UC06 Record Attendance
    @classmethod
    def validate_batch(cls, s: Store, session: ClassSession, entries: dict[str, str]) -> list[str]:
        errors = []
        eligible = {u.id: u for u in cls.eligible_students(s, session)}
        have = {r.student_id for r in session_records(s, session.id)}
        if not entries:
            errors.append("No attendance entries were submitted.")
        for student_id, status in entries.items():
            name = eligible[student_id].full_name if student_id in eligible else f"student {student_id}"
            if student_id not in eligible:
                errors.append(f"{name} is not actively enrolled on {session.session_date}.")
            elif student_id in have:
                errors.append(f"{name} already has a record (use Correct Attendance).")
            if status not in ATTENDANCE_STATUSES:
                errors.append(f"Please choose a status for {name}.")
        for sid, u in eligible.items():
            if sid not in entries and sid not in have:
                errors.append(f"Please choose a status for {u.full_name}.")
        return errors

    @classmethod
    def record_attendance(cls, s: Store, instructor: User, session_id: str, entries: dict[str, str]) -> int:
        session = cls.assigned_session(s, instructor, session_id)
        if not session.is_open():
            raise ServiceError(f"Session is {session.state}. Attendance can only be recorded for Open sessions.")
        errors = cls.validate_batch(s, session, entries)
        if errors:
            raise ServiceError("The whole batch was rejected and nothing was saved. " + " ".join(errors))
        docs = {AttendanceRecord.make_id(session_id, sid):
                AttendanceRecord(session_id=session_id, student_id=sid, status=st, updated_at=_now()).to_doc()
                for sid, st in entries.items()}
        try:
            s.create_many("records", docs)  # all-or-nothing
        except DuplicateError:
            raise ServiceError("The batch was rejected because a record already exists. Nothing was saved.")
        return len(docs)

    # ---------- UC07 Correct Attendance
    @classmethod
    def correct_attendance(cls, s: Store, instructor: User, record_id: str, status: str) -> AttendanceRecord:
        doc = s.get("records", record_id)
        if doc is None:
            raise ServiceError("Attendance record not found.")
        record = AttendanceRecord.from_doc(doc)
        session = cls.assigned_session(s, instructor, record.session_id)
        if session.is_finalized():
            raise ServiceError("This session is Finalized, so its records are locked.")
        if session.state == "Scheduled":
            raise ServiceError("This session has not been opened yet.")
        if status not in ATTENDANCE_STATUSES:
            raise ServiceError("Please choose a valid status.")
        if status == record.status:
            raise ServiceError("The new status is the same as the current status.")
        log = AttendanceCorrectionLog(record_id=record_id, previous_status=record.status, new_status=status,
                                      corrected_by=instructor.id, corrected_at=_now())
        s.write_many([("records", record_id, {"status": status, "updated_at": log.corrected_at}, "update"),
                      ("corrections", f"{record_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                       log.to_doc(), "set")])
        record.status, record.updated_at = status, log.corrected_at
        return record


# ============================================================ UC08, UC09, FR12
class ReportingService:
    @staticmethod
    def calculate_percentage(present_count: int, eligible_count: int) -> float | None:
        if eligible_count == 0:
            return None  # shown as N/A, not 0%
        return round(present_count / eligible_count * 100, 1)

    @classmethod
    def build_report(cls, s: Store, course: Course, start: date, end: date) -> AttendanceReport:
        threshold = get_policy(s).threshold
        sessions = [x for x in course_sessions(s, course.id) if x.is_finalized() and start <= x.day <= end]
        records = {(r.session_id, r.student_id): r for x in sessions for r in session_records(s, x.id)}
        report = AttendanceReport(course, start, end, threshold, len(sessions))
        by_student: dict[str, list[Enrollment]] = {}
        for e in course_enrollments(s, course.id):
            by_student.setdefault(e.student_id, []).append(e)
        students = [u for u in (get_user(s, i) for i in by_student) if u]
        for student in sorted(students, key=lambda u: u.full_name):
            enr = by_student[student.id]
            eligible = [x for x in sessions if any(e.is_active_on(x.day) for e in enr)]
            if not eligible and all(e.withdrawn_on for e in enr):
                continue  # dropped before the period
            present = sum(1 for x in eligible
                          if (r := records.get((x.id, student.id))) and r.status == "Present")
            pct = cls.calculate_percentage(present, len(eligible))
            report.add_entry(ReportRow(student, present, len(eligible), pct, pct is not None and pct < threshold))
        return report

    # ---------- UC09 Generate Attendance Report
    @classmethod
    def generate_report(cls, s: Store, instructor: User, course_id: str, start, end) -> AttendanceReport:
        course = AttendanceService.assigned_course(s, instructor, course_id)
        start_d, end_d = date.fromisoformat(_iso(start, "Start date")), date.fromisoformat(_iso(end, "End date"))
        if end_d < start_d:
            raise ServiceError("End date must be on or after the start date.")
        return cls.build_report(s, course, start_d, end_d)

    # ---------- FR12 low-attendance alerts for administrators
    @classmethod
    def low_attendance_alerts(cls, s: Store) -> list[tuple[Course, ReportRow]]:
        alerts = []
        for course in all_courses(s):
            rep = cls.build_report(s, course, date.min, date.max)
            alerts += [(course, r) for r in rep.entries if r.below_threshold]
        return alerts

    # ---------- UC08 View Attendance History
    @staticmethod
    def student_courses(s: Store, student: User) -> list[Course]:
        ids = {d["course_id"] for d in s.list("enrollments", student_id=student.id)}
        return sorted((c for c in (get_course(s, i) for i in ids) if c), key=lambda c: (c.semester, c.course_code))

    @classmethod
    def attendance_history(cls, s: Store, student: User, course_id: str):
        enr = [Enrollment.from_doc(d) for d in s.list("enrollments", student_id=student.id, course_id=course_id)]
        course = get_course(s, course_id)
        if not enr or course is None:
            raise ServiceError("Access denied: you are not enrolled in this course.")
        rows = []
        for x in course_sessions(s, course_id):
            if x.state == "Scheduled" or not any(e.is_active_on(x.day) for e in enr):
                continue
            doc = s.get("records", AttendanceRecord.make_id(x.id, student.id))
            rows.append((x, AttendanceRecord.from_doc(doc) if doc else None))
        final = [(x, r) for x, r in rows if x.is_finalized()]
        present = sum(1 for x, r in final if r and r.status == "Present")
        return course, rows, cls.calculate_percentage(present, len(final)), get_policy(s).threshold
