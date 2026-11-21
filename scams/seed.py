"""Initial data: ONLY the administrator and instructor accounts are hard-coded.

Students, courses and enrollments are created by the administrator in the app.
"""
from .security import hash_password
from .store import Store

ADMINISTRATORS = [
    {"full_name": "System Administrator", "email": "admin@ud.ac.ae",
     "password": "admin123", "employee_number": "A001"},
]

INSTRUCTORS = [
    {"full_name": "Dr. Sara Khalil", "email": "sara.khalil@ud.ac.ae", "password": "instructor123", "employee_number": "E101"},
    {"full_name": "Dr. Ahmed Hassan", "email": "ahmed.hassan@ud.ac.ae", "password": "instructor123", "employee_number": "E102"},
    {"full_name": "Dr. Omar Farouk", "email": "omar.farouk@ud.ac.ae", "password": "instructor123", "employee_number": "E103"},
    {"full_name": "Dr. Layla Mansour", "email": "layla.mansour@ud.ac.ae", "password": "instructor123", "employee_number": "E104"},
    {"full_name": "Dr. James Carter", "email": "james.carter@ud.ac.ae", "password": "instructor123", "employee_number": "E105"},
]


def seed(store: Store) -> None:
    existing = {u["email"] for u in store.list("users")}
    for role, people in (("Administrator", ADMINISTRATORS), ("Instructor", INSTRUCTORS)):
        for p in people:
            if p["email"] not in existing:
                store.add("users", {"full_name": p["full_name"], "email": p["email"],
                                    "password_hash": hash_password(p["password"]), "active": True,
                                    "role": role, "student_number": None,
                                    "employee_number": p["employee_number"]})
    if store.get("settings", "policy") is None:
        store.set("settings", "policy", {"threshold": 75.0})
