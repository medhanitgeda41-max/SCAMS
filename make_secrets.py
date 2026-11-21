"""Turns the Firebase service account key (.json) into Streamlit secrets.

Usage:  python make_secrets.py path\\to\\your-key.json

It writes .streamlit/secrets.toml (used when you run the app on your computer)
and prints the same text so you can paste it into Streamlit Cloud → Settings → Secrets.
Neither file is uploaded to GitHub (both are listed in .gitignore).
"""
import json
import sys
from pathlib import Path


def to_toml(info: dict) -> str:
    lines = ["[firebase]"]
    for key, value in info.items():
        lines.append(f"{key} = {json.dumps(value)}")  # JSON strings are valid TOML strings
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    info = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if info.get("type") != "service_account":
        sys.exit("This is not a service account key. Download it from Firebase → Project settings → "
                 "Service accounts → Generate new private key.")
    text = to_toml(info)
    out = Path(__file__).parent / ".streamlit" / "secrets.toml"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Saved {out}\n\n--- Paste everything below into Streamlit Cloud → Settings → Secrets ---\n")
    print(text)


if __name__ == "__main__":
    main()
