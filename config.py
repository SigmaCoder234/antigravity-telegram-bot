import os
import shutil
import json
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "workspace" / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Load .env file
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

# Bot Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Allowed users list (comma-separated IDs in env: "12345678,98765432")
_allowed_str = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USERS = set()
if _allowed_str:
    for item in _allowed_str.split(","):
        item = item.strip()
        if item.isdigit():
            ALLOWED_USERS.add(int(item))

# Admin ID
_admin_str = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID = int(_admin_str) if _admin_str.isdigit() else None
if ADMIN_ID:
    ALLOWED_USERS.add(ADMIN_ID)

# Defaults
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-3.7-flash-high")
DEFAULT_EFFORT = os.getenv("DEFAULT_EFFORT", "high")  # low | medium | high
DEFAULT_CWD = os.getenv("DEFAULT_CWD", str(Path.home()))
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "auto")  # auto | review

# Discover agy binary
_custom_agy = os.getenv("AGY_BIN_PATH", "")
if _custom_agy and os.path.exists(_custom_agy):
    AGY_BIN = _custom_agy
else:
    AGY_BIN = shutil.which("agy") or "/root/.local/bin/agy"

# Available Models for selector
AVAILABLE_MODELS = [
    ("gemini-3.7-flash-high", "Gemini 3.7 Flash (High) ⚡"),
    ("gemini-3.7-flash-medium", "Gemini 3.7 Flash (Medium)"),
    ("gemini-3.6-flash-high", "Gemini 3.6 Flash (High)"),
    ("gemini-3.1-pro-high", "Gemini 3.1 Pro (High) 🧠"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking) 🎯"),
    ("claude-opus-4-6-thinking", "Claude Opus 4.6 (Thinking) 👑"),
    ("gpt-oss-120b-medium", "GPT-OSS 120B (Medium)"),
]

# Sessions file
SESSIONS_FILE = DATA_DIR / "sessions.json"

def is_user_allowed(user_id: int) -> bool:
    """Check if the user is authorized. If ALLOWED_USERS is empty, anyone or first user can be allowed."""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

def add_allowed_user(user_id: int):
    """Dynamically add an allowed user and update .env."""
    ALLOWED_USERS.add(user_id)
    # Save back to .env
    lines = []
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    updated = False
    new_allowed_str = ",".join(str(uid) for uid in ALLOWED_USERS)
    new_lines = []
    for line in lines:
        if line.startswith("ALLOWED_USER_IDS="):
            new_lines.append(f"ALLOWED_USER_IDS={new_allowed_str}\n")
            updated = True
        else:
            new_lines.append(line)
    
    if not updated:
        new_lines.append(f"ALLOWED_USER_IDS={new_allowed_str}\n")
        
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
