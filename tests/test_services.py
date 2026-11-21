"""Business-rule tests for every use case, run against the in-memory store.

Run:  pytest -q
"""
import pytest

from scams.seed import seed
from scams.services import (AdministrationService as Adm, AttendanceService as Att,
                            AuthenticationService as Auth, ReportingService as Rep, ServiceError,
                            all_users, session_records)
from scams.store import MemoryStore


@pytest.fixture()
def world():
    s = MemoryStore()
    seed(s)
    admin = Auth.authenticate(s, "admin@ud.ac.ae", "admin123")
    sara = Auth.authenticate(s, "sara.khalil@ud.ac.ae", "instructor123")
    other = Auth.authenticate(s, "ahmed.hassan@ud.ac.ae", "instructor123")
    st = [Adm.create_user(s, "Student", n, e, "student123", num) for n, e, num in
          [("Eran Hadafmand", "eran@ud.ac.ae", "3703"), ("Daniel Haile", "daniel@ud.ac.ae", "3925"),
           ("Yoseph Biftu", "yoseph@ud.ac.ae", "3978")]]
    course = Adm.save_course(s, "eece324", "Software Engineering", "Fall 2026", "1", sara.id)
    for u in st:
        Adm.enroll(s, course.id, u.id, "2026-09-01")
    return s, admin, sara, other, st, course


def test_seed_only_admin_and_instructors():
    s = MemoryStore()
    seed(s)
    roles = [u.role for u in all_users(s)]
    assert roles.count("Administrator") == 1 and roles.count("Instructor") == 5 and "Student" not in roles


def test_uc01_login_rules(world):
    s, admin, *_ , st, _c = world
    with pytest.raises(ServiceError, match="Invalid"):
        Auth.authenticate(s, "admin@ud.ac.ae", "nope")
    Adm.set_active(s, admin, st[0].id, False)
    with pytest.raises(ServiceError, match="inactive"):
        Auth.authenticate(s, "eran@ud.ac.ae", "student123")
    with pytest.raises(ServiceError, match="own account"):
        Adm.set_active(s, admin, admin.id, False)


def test_uc02_uc03_uc04_validation(world):
    s, admin, sara, other, st, course = world
    with pytest.raises(ServiceError, match="already exists"):
        Adm.create_user(s, "Student", "X", "eran@ud.ac.ae", "abcdef", "1")
    with pytest.raises(ServiceError, match="already exists"):
        Adm.save_course(s, "EECE324", "SE", "Fall 2026", "1", sara.id)
    with pytest.raises(ServiceError, match="already enrolled"):
        Adm.enroll(s, course.id, st[0].id, "2026-09-02")
    with pytest.raises(ServiceError, match="active instructor"):
        Adm.save_course(s, "EECE210", "DS", "Fall 2026", "1", st[0].id)


def test_uc10_threshold(world):
    s = world[0]
    for bad in ("150", "abc", "-1"):
        with pytest.raises(ServiceError):
            Adm.update_threshold(s, bad)
    assert Adm.update_threshold(s, "80").threshold == 80


def test_full_flow(world):
    s, admin, sara, other, st, course = world
    with pytest.raises(ServiceError, match="not assigned"):
        Att.create_session(s, other, course.id, "2026-10-01")
    s1 = Att.create_session(s, sara, course.id, "2026-10-01")
    s2 = Att.create_session(s, sara, course.id, "2026-10-08")
    with pytest.raises(ServiceError, match="already exists"):
        Att.create_session(s, sara, course.id, "2026-10-01")

    entries = {st[0].id: "Present", st[1].id: "Late", st[2].id: "Absent"}
    with pytest.raises(ServiceError, match="only be recorded for Open"):
        Att.record_attendance(s, sara, s1.id, entries)
    Att.change_state(s, sara, s1.id, "open")
    with pytest.raises(ServiceError, match="whole batch"):
        Att.record_attendance(s, sara, s1.id, {st[0].id: "Present"})
    assert session_records(s, s1.id) == []
    assert Att.record_attendance(s, sara, s1.id, entries) == 3
    with pytest.raises(ServiceError, match="rejected"):
        Att.record_attendance(s, sara, s1.id, entries)

    # report before finalizing: nothing counted yet -> N/A
    rep = Rep.generate_report(s, sara, course.id, "2026-09-01", "2026-12-31")
    assert rep.finalized_sessions == 0 and all(r.percentage is None for r in rep.entries)

    Att.change_state(s, sara, s1.id, "close")
    rec = next(r for r in session_records(s, s1.id) if r.student_id == st[1].id)
    Att.correct_attendance(s, sara, rec.id, "Present")
    assert s.list("corrections", record_id=rec.id)[0]["previous_status"] == "Late"
    Att.change_state(s, sara, s1.id, "finalize")
    with pytest.raises(ServiceError, match="locked"):
        Att.correct_attendance(s, sara, rec.id, "Absent")
    with pytest.raises(ServiceError, match="Cannot open"):
        Att.change_state(s, sara, s1.id, "open")

    Att.change_state(s, sara, s2.id, "open")
    Att.change_state(s, sara, s2.id, "close")
    with pytest.raises(ServiceError, match="Cannot finalize"):
        Att.change_state(s, sara, s2.id, "finalize")

    rep = Rep.generate_report(s, sara, course.id, "2026-09-01", "2026-12-31")
    pct = {r.student.full_name: r.percentage for r in rep.entries}
    assert pct == {"Daniel Haile": 100.0, "Eran Hadafmand": 100.0, "Yoseph Biftu": 0.0}
    assert [c.course_code for c, r in Rep.low_attendance_alerts(s)] == ["EECE324"]

    yoseph = Auth.authenticate(s, "yoseph@ud.ac.ae", "student123")
    c, rows, p, thr = Rep.attendance_history(s, yoseph, course.id)
    assert p == 0.0 and rows[0][1].status == "Absent"
    with pytest.raises(ServiceError, match="not enrolled"):
        Rep.attendance_history(s, yoseph, "nope")

    # UC04: a dropped student is not eligible for later sessions
    enr = s.list("enrollments", student_id=st[1].id)[0]
    Adm.drop(s, enr["id"], "2026-10-05")
    assert st[1].id not in {u.id for u in Att.eligible_students(s, s2)}
