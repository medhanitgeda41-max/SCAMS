"""Runs the full business flow through FirestoreStore, using an in-process mock of Firestore."""
import pytest
from google.api_core.exceptions import AlreadyExists

mockfirestore = pytest.importorskip("mockfirestore")

from scams.seed import seed  # noqa: E402
from scams.services import (AdministrationService as Adm, AttendanceService as Att,  # noqa: E402
                            AuthenticationService as Auth, ReportingService as Rep, ServiceError)
from scams.store import FirestoreStore  # noqa: E402


class MockBatch:
    """Minimal stand-in for Firestore's WriteBatch (all-or-nothing on commit)."""
    def __init__(self):
        self.ops = []

    def create(self, ref, data): self.ops.append(("create", ref, data))
    def set(self, ref, data): self.ops.append(("set", ref, data))
    def update(self, ref, data): self.ops.append(("update", ref, data))

    def commit(self):
        if any(op == "create" and ref.get().exists for op, ref, _ in self.ops):
            raise AlreadyExists("document exists")
        for op, ref, data in self.ops:
            ref.update(data) if op == "update" else ref.set(data)


def test_flow_on_firestore_store():
    client = mockfirestore.MockFirestore()
    client.batch = MockBatch
    s = FirestoreStore(client)
    seed(s)
    seed(s)  # running twice must not duplicate accounts
    assert len(s.list("users", role="Instructor")) == 5
    sara = Auth.authenticate(s, "sara.khalil@ud.ac.ae", "instructor123")
    a = Adm.create_user(s, "Student", "Eran Hadafmand", "eran@ud.ac.ae", "student123", "3703")
    b = Adm.create_user(s, "Student", "Yoseph Biftu", "yoseph@ud.ac.ae", "student123", "3978")
    c = Adm.save_course(s, "EECE324", "Software Engineering", "Fall 2026", "1", sara.id)
    Adm.enroll(s, c.id, a.id, "2026-09-01")
    Adm.enroll(s, c.id, b.id, "2026-09-01")
    x = Att.create_session(s, sara, c.id, "2026-10-01")
    Att.change_state(s, sara, x.id, "open")
    assert Att.record_attendance(s, sara, x.id, {a.id: "Present", b.id: "Absent"}) == 2
    with pytest.raises(ServiceError):
        Att.record_attendance(s, sara, x.id, {a.id: "Present", b.id: "Absent"})
    Att.change_state(s, sara, x.id, "close")
    Att.correct_attendance(s, sara, f"{x.id}_{b.id}", "Late")
    Att.change_state(s, sara, x.id, "finalize")
    rep = Rep.generate_report(s, sara, c.id, "2026-09-01", "2026-12-31")
    assert {r.student.full_name: r.percentage for r in rep.entries} == {"Eran Hadafmand": 100.0, "Yoseph Biftu": 0.0}
    assert len(s.list("corrections")) == 1
