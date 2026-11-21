"""Clicks through the Streamlit app as each role (runs in demo mode, no Firebase needed)."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


def first(widgets, label):
    return next(w for w in widgets if w.label == label)


def button(at, label):
    return first(at.button, label)


def login(email, password, at=None):
    """Log in; reuse the same app session so the in-memory data is shared between roles."""
    if at is None:
        at = AppTest.from_file(APP, default_timeout=60).run()
    else:
        first(at.sidebar.button, "Log out").click().run()
    at.text_input(key="login_email").input(email)
    at.text_input(key="login_password").input(password)
    button(at, "Log in").click().run()
    assert not at.exception, at.exception
    return at


def go(at, page):
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception


def messages(at):
    return " ".join(m.value for m in list(at.success) + list(at.error) + list(at.warning) + list(at.info))


def test_three_roles_end_to_end():
    # ---------------- administrator
    at = login("admin@ud.ac.ae", "admin123")
    assert at.header[0].value == "Dashboard"
    go(at, "Users")
    for name, email, num in [("Eran Hadafmand", "eran@ud.ac.ae", "3703"), ("Yoseph Biftu", "yoseph@ud.ac.ae", "3978")]:
        first(at.selectbox, "Role").set_value("Student")
        first(at.text_input, "Full name").input(name)
        first(at.text_input, "Email").input(email)
        first(at.text_input, "Student ID / employee number").input(num)
        first(at.text_input, "Password (min. 6 characters)").input("student123")
        button(at, "Create account").click().run()
        assert f"account created for {name}" in messages(at)

    go(at, "Courses")
    first(at.text_input, "Course code").input("EECE324")
    first(at.text_input, "Course name").input("Software Engineering")
    first(at.text_input, "Semester").input("Fall 2026")
    sel = at.selectbox(key="new_course_instr")
    sel.select_index(next(i for i, o in enumerate(sel.options) if "Sara" in o))
    E = at
    button(E, "Create course").click().run()
    assert "Course EECE324 created" in messages(E)

    go(E, "Enrollments")
    for _ in range(2):
        button(E, "Enroll").click().run()
        assert "enrolled" in messages(E)

    # ---------------- instructor
    at = login("sara.khalil@ud.ac.ae", "instructor123", at)
    first(at.date_input, "Session date").set_value("2026-11-23").run()
    button(at, "Create session").click().run()
    assert "created in Scheduled state" in messages(at)
    button(at, "Open session").click().run()
    assert "is now Open" in messages(at)
    button(at, "Submit attendance batch").click().run()
    assert "whole batch was rejected" in messages(at)
    radios = [r for r in at.radio if r.label.startswith(("Eran", "Yoseph"))]
    for r in radios:
        r.set_value("Present" if r.label.startswith("Eran") else "Absent")
    button(at, "Submit attendance batch").click().run()
    assert "saved for 2 student" in messages(at)
    button(at, "Close session").click().run()
    button(at, "Finalize session").click().run()
    assert "is now Finalized" in messages(at)
    go(at, "Attendance report")
    button(at, "Generate report").click().run()
    df = at.dataframe[0].value
    assert set(df["Attendance"]) == {"100.0%", "0.0%"}

    # ---------------- student
    at = login("yoseph@ud.ac.ae", "student123", at)
    assert at.metric[0].value == "0.0%"
    assert "below the required threshold" in messages(at)
