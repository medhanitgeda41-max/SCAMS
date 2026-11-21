# Smart Campus Attendance Management System (Streamlit + Firestore)

A Streamlit web app built from the EECE 324 project report, with three roles (**Administrator**, **Instructor** and **Student**). Data is stored in **Google Cloud Firestore**.

If Firebase isn't connected yet, the app still runs in **demo mode** and keeps data in memory. Demo data is lost when the app restarts.

---

## 1. Set up Firebase (once)

1. Open https://console.firebase.google.com and select your project (**scams-8c092**).
2. In the left menu, go to **Build → Firestore Database → Create database**. Choose **Production mode** and a location close to you (for example `me-central1`).
3. Click the gear icon, then **Project settings → Service accounts → Generate new private key**. A `.json` file downloads.
   **This file is a password to your database. Never upload it to GitHub or share it.**

## 2. Run it on your computer

Open PowerShell **in this folder** (the one that contains `streamlit_app.py`), then run:

```powershell
pip install -r requirements.txt
python make_secrets.py "C:\Users\Student\Downloads\your-key-file.json"
streamlit run streamlit_app.py
```

`make_secrets.py` creates `.streamlit/secrets.toml` from your key and prints the text you'll need in step 4. The app opens at http://localhost:8501. The sidebar should show **Database: Firestore**.

## 3. Upload the code to GitHub

1. Go to https://github.com/new, enter a name (for example `scams-attendance`) and click **Create repository**.
2. Click **uploading an existing file**, then drag in everything in this folder **except** these:
   - your Firebase key `.json` file
   - `.streamlit/secrets.toml`
3. Click **Commit changes**.

Or with Git (the `.gitignore` file already keeps the secrets out):
```powershell
git init
git add .
git commit -m "Smart Campus Attendance app"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/scams-attendance.git
git push -u origin main
```

## 4. Publish on Streamlit Community Cloud

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app → Deploy a public app from GitHub**.
3. Choose your repository, branch `main`, and main file path `streamlit_app.py`.
4. Open **Advanced settings → Secrets** and paste the text that `make_secrets.py` printed (it starts with `[firebase]`).
5. Click **Deploy**. After a minute or two you get a public link like `https://scams-attendance.streamlit.app`.

If you change the secrets later, go to **App → Settings → Secrets**, save, and the app restarts.

---

## Built-in accounts

Only the administrator and instructor accounts are hard-coded (`scams/seed.py`). They're created in Firestore the first time the app starts. Students, courses and enrollments are created by the administrator in the app.

| Role | Email | Password |
|---|---|---|
| Administrator | admin@ud.ac.ae | admin123 |
| Instructor | sara.khalil@ud.ac.ae | instructor123 |
| Instructor | ahmed.hassan@ud.ac.ae | instructor123 |
| Instructor | omar.farouk@ud.ac.ae | instructor123 |
| Instructor | layla.mansour@ud.ac.ae | instructor123 |
| Instructor | james.carter@ud.ac.ae | instructor123 |

## How the code follows the report

| Report | Code |
|---|---|
| Presentation layer | `streamlit_app.py` |
| Application layer: controller classes | `scams/services.py`: `AuthenticationService`, `AdministrationService`, `AttendanceService`, `ReportingService` |
| Application layer: entity classes (Figure 4.1) | `scams/models.py`: `User`, `Course`, `Enrollment`, `ClassSession`, `AttendanceRecord`, `AttendanceCorrectionLog`, `AttendancePolicy` |
| Data layer | `scams/store.py`: `FirestoreStore` (Firestore) and `MemoryStore` (demo mode) |
| State machine (Figure 5.2) | `ClassSession.open()`, `close()`, `reopen()`, `finalize_session()` |

**Firestore collections:** `users`, `courses`, `enrollments`, `sessions`, `records`, `corrections`, `settings`.
Each attendance record's ID is `<sessionId>_<studentId>`, so a student can only have one record per session (NFR04). A batch of attendance is saved with one Firestore batch write, so it's all-or-nothing.

## Business rules

- **Access:** each role only sees its own pages, and instructors only see the courses assigned to them.
- **Sessions:** one session per course per day. Sessions go Scheduled → Open → Closed → Finalized, and a Closed session can be reopened. A session can only be finalized when every eligible student has a record.
- **Corrections:** allowed while a session is Open or Closed, and locked once it's Finalized. Every correction is logged.
- **Percentage:** Present ÷ eligible finalized sessions. Late, Absent and Excused don't count as attended. A student with no eligible sessions shows N/A instead of 0%.
- **Enrollment dates:** a student only counts for sessions held while their enrollment was active.
- **Threshold:** must be from 0 to 100. Students below it appear on the administrator's Alerts page.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest -q
```
