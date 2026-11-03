import json
import os
import time
import uuid
import asyncio
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field, asdict
from pathlib import Path
import config

@dataclass
class ChatConversation:
    id: str
    title: str
    created_at: float
    updated_at: float
    cwd: str
    message_count: int = 0
    claude_session_id: Optional[str] = None  # Claude Code session to --resume

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cwd": self.cwd,
            "message_count": self.message_count,
            "claude_session_id": self.claude_session_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatConversation":
        return cls(
            id=data["id"],
            title=data.get("title", "Новый диалог"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            cwd=data.get("cwd", config.DEFAULT_CWD),
            message_count=data.get("message_count", 0),
            claude_session_id=data.get("claude_session_id"),
        )


@dataclass
class UserSession:
    user_id: int
    active_conv_id: Optional[str] = None
    conversations: Dict[str, ChatConversation] = field(default_factory=dict)
    cwd: str = config.DEFAULT_CWD
    model: str = config.DEFAULT_MODEL
    effort: str = config.DEFAULT_EFFORT
    mode: str = config.DEFAULT_MODE  # 'auto' or 'review'
    
    # Runtime fields (not persisted)
    active_runner: Any = field(default=None, repr=False)
    active_task: Optional[asyncio.Task] = field(default=None, repr=False)
    waiting_input_future: Optional[asyncio.Future] = field(default=None, repr=False)
    waiting_input_prompt: Optional[str] = field(default=None, repr=False)
    waiting_rename_conv_id: Optional[str] = field(default=None, repr=False)

    @property
    def conversation_id(self) -> Optional[str]:
        return self.active_conv_id

    @conversation_id.setter
    def conversation_id(self, val: Optional[str]):
        self.active_conv_id = val

    def get_active_conv(self) -> Optional[ChatConversation]:
        if self.active_conv_id and self.active_conv_id in self.conversations:
            return self.conversations[self.active_conv_id]
        return None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "active_conv_id": self.active_conv_id,
            "conversations": {cid: c.to_dict() for cid, c in self.conversations.items()},
            "cwd": self.cwd,
            "model": self.model,
            "effort": self.effort,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserSession":
        cwd = data.get("cwd", config.DEFAULT_CWD)
        if not os.path.exists(cwd):
            cwd = config.DEFAULT_CWD
        
        convs = {}
        if "conversations" in data and isinstance(data["conversations"], dict):
            for cid, cdata in data["conversations"].items():
                convs[cid] = ChatConversation.from_dict(cdata)
        elif "conversation_id" in data and data["conversation_id"]:
            # Migrate older format
            cid = data["conversation_id"]
            convs[cid] = ChatConversation(
                id=cid,
                title="Диалог",
                created_at=time.time(),
                updated_at=time.time(),
                cwd=cwd,
                message_count=1
            )

        active_id = data.get("active_conv_id") or data.get("conversation_id")
        if active_id and active_id not in convs:
            active_id = list(convs.keys())[0] if convs else None

        return cls(
            user_id=data["user_id"],
            active_conv_id=active_id,
            conversations=convs,
            cwd=cwd,
            model=config.normalize_model(data.get("model")),
            effort=data.get("effort", config.DEFAULT_EFFORT),
            mode=data.get("mode", config.DEFAULT_MODE),
        )


class SessionManager:
    def __init__(self, storage_file: Path = config.SESSIONS_FILE):
        self.storage_file = storage_file
        self.sessions: Dict[int, UserSession] = {}
        self._load()

    def _load(self):
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for uid_str, sdata in data.items():
                        uid = int(uid_str)
                        self.sessions[uid] = UserSession.from_dict(sdata)
            except Exception as e:
                print(f"[SessionManager] Error loading sessions: {e}")

    def save(self):
        try:
            data = {str(uid): s.to_dict() for uid, s in self.sessions.items()}
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SessionManager] Error saving sessions: {e}")

    def get_session(self, user_id: int) -> UserSession:
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id=user_id)
            self.save()
        return self.sessions[user_id]

    def create_new_conversation(self, user_id: int, title: str = "Новый диалог") -> ChatConversation:
        session = self.get_session(user_id)
        conv_id = str(uuid.uuid4())
        conv = ChatConversation(
            id=conv_id,
            title=title,
            created_at=time.time(),
            updated_at=time.time(),
            cwd=session.cwd,
            message_count=0
        )
        session.conversations[conv_id] = conv
        session.active_conv_id = conv_id
        self.save()
        return conv

    def switch_conversation(self, user_id: int, conv_id: str) -> bool:
        session = self.get_session(user_id)
        if conv_id in session.conversations:
            session.active_conv_id = conv_id
            session.cwd = session.conversations[conv_id].cwd
            self.save()
            return True
        return False

    def delete_conversation(self, user_id: int, conv_id: str) -> bool:
        session = self.get_session(user_id)
        if conv_id in session.conversations:
            del session.conversations[conv_id]
            if session.active_conv_id == conv_id:
                session.active_conv_id = list(session.conversations.keys())[0] if session.conversations else None
            self.save()
            return True
        return False

    def rename_conversation(self, user_id: int, conv_id: str, new_title: str) -> bool:
        session = self.get_session(user_id)
        if conv_id in session.conversations:
            session.conversations[conv_id].title = new_title[:50].strip()
            self.save()
            return True
        return False

    def record_turn(self, user_id: int, prompt_text: str, conv_id: Optional[str]):
        session = self.get_session(user_id)
        if not conv_id:
            return

        if conv_id not in session.conversations:
            # Create entry for new conversation
            session.conversations[conv_id] = ChatConversation(
                id=conv_id,
                title=prompt_text[:30].strip() or "Диалог",
                created_at=time.time(),
                updated_at=time.time(),
                cwd=session.cwd,
                message_count=1
            )
            session.active_conv_id = conv_id
        else:
            conv = session.conversations[conv_id]
            conv.updated_at = time.time()
            conv.message_count += 1
            if conv.title == "Новый диалог" or conv.title == "Диалог":
                clean_title = prompt_text.replace("\n", " ").strip()
                conv.title = clean_title[:30] + ("..." if len(clean_title) > 30 else "")
        self.save()

    def reset_session(self, user_id: int):
        session = self.get_session(user_id)
        if session.active_runner and hasattr(session.active_runner, "cancel"):
            try:
                session.active_runner.cancel()
            except Exception:
                pass
        if session.active_task and not session.active_task.done():
            session.active_task.cancel()

        session.active_runner = None
        session.active_task = None
        session.waiting_input_future = None
        session.waiting_input_prompt = None
        session.waiting_rename_conv_id = None
        
        # Start a brand new conversation
        self.create_new_conversation(user_id, title="Новый диалог")

    def set_cwd(self, user_id: int, new_cwd: str) -> bool:
        path = Path(new_cwd).expanduser().resolve()
        if path.is_dir():
            session = self.get_session(user_id)
            session.cwd = str(path)
            conv = session.get_active_conv()
            if conv:
                conv.cwd = str(path)
            self.save()
            return True
        return False

    def set_model(self, user_id: int, model: str):
        session = self.get_session(user_id)
        session.model = model
        self.save()

    def set_effort(self, user_id: int, effort: str):
        session = self.get_session(user_id)
        session.effort = effort
        self.save()

    def set_mode(self, user_id: int, mode: str):
        session = self.get_session(user_id)
        session.mode = mode
        self.save()


# Singleton
session_manager = SessionManager()
