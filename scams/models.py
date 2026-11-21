"""Entity classes from the design class diagram (Figure 4.1).

Each class is built from a Firestore document (from_doc) and turned back
into one (to_doc). Dates are stored as "YYYY-MM-DD" text.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

SESSION_STATES = ["Scheduled", "Open", "Closed", "Finalized"]          # SessionState
ATTENDANCE_STATUSES = ["Present", "Absent", "Late", "Excused"]          # AttendanceStatus
ROLES = ["Student", "Instructor", "Administrator"]                      # User subclasses


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass
class Doc:
    id: str = ""

    @classmethod
    def from_doc(cls, doc: dict):
        names = cls.__dataclass_fields__
        return cls(**{k: v for k, v in doc.items() if k in names})

    def to_doc(self) -> dict:
        data = asdict(self)
        data.pop("id")
        return data


@dataclass
class User(Doc):
    """Abstract user; role is Student, Instructor or Administrator."""
    full_name: str = ""
    email: str = ""
    password_hash: str = ""
    active: bool = True
    role: str = "Student"
    student_number: str | None = None
    employee_number: str | None = None

    def is_active(self) -> bool:
        return self.active

    @property
    def number(self) -> str:
        return self.student_number or self.employee_number or ""


@dataclass
class Course(Doc):
    course_code: str = ""
    course_name: str = ""
    semester: str = ""
    section: str = "1"
    instructor_id: str | None = None

    @property
    def label(self) -> str:
        return f"{self.course_code} – {self.course_name} (Sec {self.section}, {self.semester})"

    def is_assigned_to(self, instructor_id: str) -> bool:
        return self.instructor_id == instructor_id


@dataclass
class Enrollment(Doc):
    student_id: str = ""
    course_id: str = ""
    enrolled_on: str = ""
    withdrawn_on: str | None = None

    def is_active_on(self, on: date) -> bool:
        return _d(self.enrolled_on) <= on and (self.withdrawn_on is None or on < _d(self.withdrawn_on))


@dataclass
class ClassSession(Doc):
    course_id: str = ""
    session_date: str = ""
    details: str = ""
    state: str = "Scheduled"

    @property
    def day(self) -> date:
        return _d(self.session_date)

    # state machine (Figure 5.2): each returns False when the change is not allowed
    def open(self) -> bool:
        return self._move("Scheduled", "Open")

    def close(self) -> bool:
        return self._move("Open", "Closed")

    def reopen(self) -> bool:
        return self._move("Closed", "Open")

    def finalize_session(self) -> bool:
        return self._move("Closed", "Finalized")

    def _move(self, frm: str, to: str) -> bool:
        if self.state != frm:
            return False
        self.state = to
        return True

    def is_open(self) -> bool:
        return self.state == "Open"

    def is_finalized(self) -> bool:
        return self.state == "Finalized"


@dataclass
class AttendanceRecord(Doc):
    """Document id is '<session_id>_<student_id>', so a student can only have one record per session."""
    session_id: str = ""
    student_id: str = ""
    status: str = "Present"
    updated_at: str = ""

    @staticmethod
    def make_id(session_id: str, student_id: str) -> str:
        return f"{session_id}_{student_id}"


@dataclass
class AttendanceCorrectionLog(Doc):
    record_id: str = ""
    previous_status: str = ""
    new_status: str = ""
    corrected_by: str = ""
    corrected_at: str = ""


@dataclass
class AttendancePolicy(Doc):
    threshold: float = 75.0


@dataclass
class ReportRow:
    student: User
    present: int
    eligible: int
    percentage: float | None
    below_threshold: bool


@dataclass
class AttendanceReport:
    course: Course
    start: date
    end: date
    threshold: float
    finalized_sessions: int
    entries: list[ReportRow] = field(default_factory=list)

    def add_entry(self, row: ReportRow) -> None:
        self.entries.append(row)
