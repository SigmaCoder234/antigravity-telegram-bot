import os
import shutil
import shlex
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
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "opus")
DEFAULT_EFFORT = os.getenv("DEFAULT_EFFORT", "high")  # low | medium | high | xhigh | max
DEFAULT_CWD = os.getenv("DEFAULT_CWD", str(Path.home()))
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "auto")  # auto | review

# Optional model to fall back to when the primary one is overloaded (e.g. "sonnet")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "").strip()

# Optional per-turn spending cap in USD (only applies to API-key billing), e.g. "2.5"
MAX_BUDGET_USD = os.getenv("MAX_BUDGET_USD", "").strip()

# Extra raw CLI arguments appended to every claude call (space-separated, shell-quoted)
CLAUDE_EXTRA_ARGS = shlex.split(os.getenv("CLAUDE_EXTRA_ARGS", ""))

# Discover the Claude Code binary
_custom_claude = os.getenv("CLAUDE_BIN_PATH", "").strip()
if _custom_claude and os.path.exists(_custom_claude):
    CLAUDE_BIN = _custom_claude
else:
    CLAUDE_BIN = (
        shutil.which("claude")
        or next(
            (p for p in (
                str(Path.home() / ".local" / "bin" / "claude"),
                str(Path.home() / ".claude" / "local" / "claude"),
                "/usr/local/bin/claude",
                "/usr/bin/claude",
            ) if os.path.exists(p)),
            "claude",
        )
    )

# Available Models for selector (aliases always point to the latest version)
AVAILABLE_MODELS = [
    ("opus", "Claude Opus (latest) 👑"),
    ("sonnet", "Claude Sonnet (latest) 🎯"),
    ("haiku", "Claude Haiku (latest) ⚡"),
    ("fable", "Claude Fable (latest) 🧠"),
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("claude-haiku-5-5", "Claude Haiku 5.5"),
    ("claude-fable-5-1", "Claude Fable 5.1"),
]

# Reasoning effort levels supported by Claude Code (--effort)
AVAILABLE_EFFORTS = [
    ("low", "Low (Быстрый ответ) ⚡"),
    ("medium", "Medium (Сбалансированный) ⚖️"),
    ("high", "High (Глубокое размышление) 🧠"),
    ("xhigh", "XHigh (Очень глубокое) 🔬"),
    ("max", "Max (Максимум) 🚀"),
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
