import asyncio
import json
import logging
import os
import re
import time
from typing import Dict, Any, Optional, Tuple
from aiogram import Bot

import config

logger = logging.getLogger("ClaudeBot.QuotaManager")

class QuotaManager:
    """
    Manages detection of quota exhaustion and notifies users when quota resets.
    """
    def __init__(self):
        # Key: (user_id, model) -> dict of details
        self._waiting: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None

    def detect_quota_error(self, error_text: str) -> Tuple[bool, Optional[float]]:
        """
        Analyzes error string to determine if it is a quota/rate limit error,
        and extracts estimated seconds until reset if provided.
        """
        if not error_text:
            return False, None

        err_lower = error_text.lower()
        quota_keywords = [
            "resource_exhausted",
            "quota exceeded",
            "quota_exceeded",
            "rate limit",
            "rate_limit",
            "too many requests",
            "429",
            "exceeded your current quota",
            "quota metric",
            "out of quota",
            "quota limit reached",
            "free quota exhausted",
            "capacity exceeded",
            "exhausted",
            "usage limit",
            "hit your limit",
            "limit reached",
            "overloaded",
        ]

        is_quota = any(kw in err_lower for kw in quota_keywords)
        if not is_quota:
            return False, None

        # Try to parse reset duration (seconds / minutes / hours)
        seconds_estimate = 60.0  # default check after 60s

        # Pattern: "try again in 45s", "reset in 5m", "retry after 120"
        m = re.search(r'(?:try again in|resets? in|retry after)\s*(\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?|h|hours?)?', err_lower)
        if m:
            val = float(m.group(1))
            unit = (m.group(2) or "s").lower()
            if unit.startswith("m"):
                seconds_estimate = val * 60
            elif unit.startswith("h"):
                seconds_estimate = val * 3600
            else:
                seconds_estimate = val
        elif re.search(r'\|(\d{10})\b', error_text):
            epoch = int(re.search(r'\|(\d{10})\b', error_text).group(1))
            diff = epoch - time.time()
            if diff > 0:
                seconds_estimate = diff
        elif re.search(r'resets?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)', err_lower):
            m_ampm = re.search(r'resets?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)', err_lower)
            try:
                import datetime
                hour = int(m_ampm.group(1)) % 12 + (12 if m_ampm.group(3) == "pm" else 0)
                minute = int(m_ampm.group(2) or 0)
                now_dt = datetime.datetime.now()
                target_dt = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target_dt < now_dt:
                    target_dt += datetime.timedelta(days=1)
                seconds_estimate = (target_dt - now_dt).total_seconds()
            except Exception:
                pass
        else:
            # Pattern: "reset at 14:30"
            m_time = re.search(r'resets?\s*(?:at|after)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?', err_lower)
            if m_time:
                try:
                    import datetime
                    now_dt = datetime.datetime.now()
                    target_hour = int(m_time.group(1))
                    target_min = int(m_time.group(2))
                    target_sec = int(m_time.group(3) or 0)
                    target_dt = now_dt.replace(hour=target_hour, minute=target_min, second=target_sec, microsecond=0)
                    if target_dt < now_dt:
                        target_dt += datetime.timedelta(days=1)
                    diff = (target_dt - now_dt).total_seconds()
                    if diff > 0:
                        seconds_estimate = diff
                except Exception:
                    pass

        return True, max(15.0, seconds_estimate)

    async def register_quota_exceeded(
        self,
        user_id: int,
        chat_id: int,
        model: str,
        conv_title: str,
        error_text: str
    ) -> float:
        """
        Registers that a user encountered a quota limit for a specific model.
        Returns the estimated wait time in seconds.
        """
        _, est_seconds = self.detect_quota_error(error_text)
        est_seconds = est_seconds or 60.0
        reset_time = time.time() + est_seconds

        async with self._lock:
            key = (user_id, model)
            self._waiting[key] = {
                "user_id": user_id,
                "chat_id": chat_id,
                "model": model,
                "conv_title": conv_title,
                "first_detected_at": time.time(),
                "estimated_reset_at": reset_time,
                "last_checked_at": 0.0,
                "is_checking": False,
            }

        logger.info(
            f"Quota exceeded registered for user_id={user_id}, model={model}. "
            f"Estimated reset in {est_seconds:.0f}s."
        )
        return est_seconds

    async def is_waiting_for_quota(self, user_id: int, model: Optional[str] = None) -> bool:
        async with self._lock:
            if model:
                return (user_id, model) in self._waiting
            return any(k[0] == user_id for k in self._waiting.keys())

    async def get_quota_info(self, user_id: int, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        async with self._lock:
            if model:
                return self._waiting.get((user_id, model))
            for (uid, m), info in self._waiting.items():
                if uid == user_id:
                    return info
            return None

    async def probe_model_quota(self, model: str) -> Tuple[bool, Optional[str]]:
        """
        Executes a minimal test query using Claude Code to test if the quota is restored.
        Returns (is_restored, error_msg).
        """
        cmd = [
            config.CLAUDE_BIN,
            "-p", "Reply with the single word: pong",
            "--model", model,
            "--output-format", "json",
            "--no-session-persistence",
            "--tools", "",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=config.DEFAULT_CWD,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=60.0)
            out_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            err_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            combined = f"{out_str}\n{err_str}"
            is_quota, _ = self.detect_quota_error(combined)
            if is_quota:
                return False, combined

            # If json output has error status with quota
            if out_str:
                try:
                    data = json.loads(out_str)
                    err = data.get("error", "") or (data.get("result", "") if data.get("is_error") else "")
                    if err:
                        is_q, _ = self.detect_quota_error(err)
                        if is_q:
                            return False, err
                except Exception:
                    pass

            return True, None
        except asyncio.TimeoutError:
            return False, "Timeout probing model"
        except Exception as e:
            return False, str(e)

    async def start_monitor_loop(self, bot: Bot):
        """
        Background task loop that checks models and notifies users when quota resets.
        """
        logger.info("Quota monitor background loop started.")
        while True:
            try:
                await asyncio.sleep(20)
                now = time.time()
                
                # Snapshot of items to check
                items_to_check = []
                async with self._lock:
                    for key, info in list(self._waiting.items()):
                        if now >= info["estimated_reset_at"] and not info.get("is_checking", False):
                            info["is_checking"] = True
                            items_to_check.append((key, dict(info)))

                for key, info in items_to_check:
                    user_id, model = key
                    chat_id = info["chat_id"]
                    conv_title = info["conv_title"]

                    logger.info(f"Probing quota availability for model {model} (user {user_id})...")
                    is_restored, err = await self.probe_model_quota(model)

                    if is_restored:
                        logger.info(f"Quota successfully restored for model {model} (user {user_id})!")
                        async with self._lock:
                            self._waiting.pop(key, None)

                        # Send notification to user in Telegram
                        notify_text = (
                            f"🔔 <b>Лимит обнулился!</b>\n\n"
                            f"Лимит запросов для модели <code>{model}</code> успешно сброшен. "
                            f"Модель снова готова к работе!\n\n"
                            f"💬 Вы можете продолжить диалог в чате <b>«{conv_title}»</b>."
                        )
                        try:
                            from utils import safe_send_message, get_persistent_keyboard
                            await safe_send_message(
                                bot=bot,
                                chat_id=chat_id,
                                text=notify_text,
                                parse_mode="HTML",
                                reply_markup=get_persistent_keyboard(conv_title)
                            )
                        except Exception as ex:
                            logger.error(f"Failed to send quota reset notification: {ex}")
                    else:
                        # Still exhausted; update next check time
                        _, next_est = self.detect_quota_error(err or "")
                        delay = next_est if next_est else 45.0
                        logger.info(f"Quota still exhausted for {model}. Next probe in {delay:.0f}s.")
                        async with self._lock:
                            if key in self._waiting:
                                self._waiting[key]["estimated_reset_at"] = time.time() + delay
                                self._waiting[key]["is_checking"] = False
                                self._waiting[key]["last_checked_at"] = time.time()

            except asyncio.CancelledError:
                logger.info("Quota monitor task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in quota monitor loop: {e}", exc_info=True)
                await asyncio.sleep(10)


quota_manager = QuotaManager()
