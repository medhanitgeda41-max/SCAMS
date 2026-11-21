"""Data layer: where documents are kept.

FirestoreStore keeps data in Google Cloud Firestore (used when Firebase
credentials are configured). MemoryStore keeps data in memory so the app
and tests can run without Firebase; its data is lost when the app restarts.

Collections: users, courses, enrollments, sessions, records, corrections, settings
"""
from __future__ import annotations

import copy
import threading
import uuid


class DuplicateError(Exception):
    """A document that must be unique already exists."""


class Store:
    def get(self, col: str, doc_id: str) -> dict | None: ...
    def list(self, col: str, **equals) -> list[dict]: ...
    def add(self, col: str, data: dict) -> str: ...
    def set(self, col: str, doc_id: str, data: dict) -> None: ...
    def update(self, col: str, doc_id: str, data: dict) -> None: ...
    def create_many(self, col: str, docs: dict[str, dict]) -> None:
        """Create several documents all-or-nothing. Raises DuplicateError if any id exists."""
    def write_many(self, writes: list[tuple[str, str, dict, str]]) -> None:
        """Apply several writes atomically. Each write is (collection, id, data, "set"|"update")."""


class MemoryStore(Store):
    def __init__(self):
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def _col(self, col):
        return self._data.setdefault(col, {})

    def get(self, col, doc_id):
        doc = self._col(col).get(doc_id)
        return {**copy.deepcopy(doc), "id": doc_id} if doc is not None else None

    def list(self, col, **equals):
        return [{**copy.deepcopy(d), "id": i} for i, d in self._col(col).items()
                if all(d.get(k) == v for k, v in equals.items())]

    def add(self, col, data):
        doc_id = uuid.uuid4().hex[:20]
        self._col(col)[doc_id] = copy.deepcopy(data)
        return doc_id

    def set(self, col, doc_id, data):
        self._col(col)[doc_id] = copy.deepcopy(data)

    def update(self, col, doc_id, data):
        self._col(col)[doc_id].update(copy.deepcopy(data))

    def create_many(self, col, docs):
        with self._lock:
            if any(i in self._col(col) for i in docs):
                raise DuplicateError("A document already exists.")
            for i, d in docs.items():
                self._col(col)[i] = copy.deepcopy(d)

    def write_many(self, writes):
        with self._lock:
            for col, doc_id, data, mode in writes:
                if mode == "update":
                    self._col(col)[doc_id].update(copy.deepcopy(data))
                else:
                    self._col(col)[doc_id] = copy.deepcopy(data)


class FirestoreStore(Store):
    def __init__(self, client):
        self.db = client

    @classmethod
    def from_service_account(cls, info: dict) -> "FirestoreStore":
        import firebase_admin
        from firebase_admin import credentials, firestore

        name = "scams"
        try:
            app = firebase_admin.get_app(name)
        except ValueError:
            app = firebase_admin.initialize_app(credentials.Certificate(dict(info)), name=name)
        return cls(firestore.client(app))

    def get(self, col, doc_id):
        snap = self.db.collection(col).document(doc_id).get()
        return {**snap.to_dict(), "id": snap.id} if snap.exists else None

    def list(self, col, **equals):
        query = self.db.collection(col)
        for key, value in equals.items():
            query = query.where(key, "==", value)
        return [{**s.to_dict(), "id": s.id} for s in query.stream()]

    def add(self, col, data):
        ref = self.db.collection(col).document()
        ref.set(data)
        return ref.id

    def set(self, col, doc_id, data):
        self.db.collection(col).document(doc_id).set(data)

    def update(self, col, doc_id, data):
        self.db.collection(col).document(doc_id).update(data)

    def create_many(self, col, docs):
        from google.api_core.exceptions import AlreadyExists, Conflict

        batch = self.db.batch()  # a batch either fully succeeds or fully fails
        for doc_id, data in docs.items():
            batch.create(self.db.collection(col).document(doc_id), data)
        try:
            batch.commit()
        except (AlreadyExists, Conflict) as exc:
            raise DuplicateError("A document already exists.") from exc

    def write_many(self, writes):
        batch = self.db.batch()
        for col, doc_id, data, mode in writes:
            ref = self.db.collection(col).document(doc_id)
            batch.update(ref, data) if mode == "update" else batch.set(ref, data)
        batch.commit()
