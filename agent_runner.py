import asyncio
import json
import os
import signal
import time
import html
import logging
from typing import Optional, Callable, Dict, Any, List

import config
from session_manager import UserSession, session_manager
from quota_manager import quota_manager

logger = logging.getLogger("ClaudeBot.AgentRunner")

# Claude Code stream-json lines may contain large tool results; raise the reader limit.
STREAM_LIMIT = 32 * 1024 * 1024

REVIEW_MODE_PROMPT = (
    "Ты работаешь через Telegram-бота в РЕЖИМЕ С ПОДТВЕРЖДЕНИЯМИ. "
    "Если для решения задачи требуется запуск bash-команд на сервере или изменение файлов, "
    "сначала опиши пользователю предлагаемые шаги/команды и спроси его согласие. "
    "Выполняй их только после явного подтверждения в следующем сообщении."
)

TELEGRAM_PROMPT = (
    "Ты отвечаешь пользователю через Telegram-бота. Пиши ответы на языке пользователя, "
    "используй обычный Markdown (заголовки, списки, блоки кода), избегай очень длинных таблиц. "
    "Если создаёшь файлы, которые пользователь должен получить, сообщи их абсолютные пути."
)


def is_effort_supported_for_model(model_name: Optional[str]) -> bool:
    """
    Claude Code supports --effort (low, medium, high, xhigh, max) for current
    Opus / Sonnet / Fable models. Haiku models use built-in reasoning.
    """
    if not model_name:
        return True
    return "haiku" not in model_name.lower()


def describe_tool(tool_name: str, params: Dict[str, Any]) -> str:
    """Human-readable (HTML) description of a Claude Code tool call."""
    name = str(tool_name or "")
    esc = html.escape
    if name == "Bash":
        cmd_preview = esc(str(params.get("command", ""))[:80])
        return f"💻 Выполняю команду: <code>{cmd_preview}</code>"
    if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = params.get("file_path") or params.get("notebook_path") or ""
        base_name = esc(os.path.basename(str(path)))
        verb = "Читаю файл" if name == "Read" else "Изменяю файл"
        return f"📝 {verb}: <code>{base_name}</code>"
    if name in ("Glob", "Grep"):
        pattern = esc(str(params.get("pattern", ""))[:60])
        return f"🔎 Поиск по файлам: <code>{pattern}</code>"
    if name == "LS":
        return f"📂 Читаю каталог: <code>{esc(str(params.get('path', '.')))}</code>"
    if name == "WebSearch":
        return f"🔍 Ищу в сети: <code>{esc(str(params.get('query', ''))[:60])}</code>"
    if name == "WebFetch":
        return f"🌐 Открываю страницу: <code>{esc(str(params.get('url', ''))[:80])}</code>"
    if name in ("Task", "Agent"):
        desc = esc(str(params.get("description", ""))[:60])
        return f"🧩 Запускаю субагента: <i>{desc}</i>"
    if name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "🗒️ Обновляю план задач"
    if name.startswith("mcp__"):
        return f"🔌 MCP-инструмент: <b>{esc(name)}</b>"
    return f"⚙️ Инструмент: <b>{esc(name)}</b>"


class AgentRunner:
    """
    Runs a single Claude Code (`claude -p`) turn in stream-json mode.

    - persist_session=True: the turn continues (or starts) the active chat's
      Claude session and stores its session id.
    - persist_session=False: an ephemeral side-turn (/btw). If the chat already
      has a session it is forked, so the main context stays untouched.
    """

    def __init__(
        self,
        session: UserSession,
        prompt: str,
        chat_id: Optional[int] = None,
        on_status: Optional[Callable[[str], Any]] = None,
        extra_flags: Optional[List[str]] = None,
        permission_mode: Optional[str] = None,
        persist_session: bool = True,
    ):
        self.session = session
        self.prompt = prompt
        self.chat_id = chat_id or session.user_id
        self.on_status = on_status
        self.extra_flags = extra_flags or []
        self.permission_mode = permission_mode
        self.persist_session = persist_session
        self.process: Optional[asyncio.subprocess.Process] = None
        self._cancelled = False
        self.last_status_time = 0.0
        self.current_status_text = ""

    async def _notify_status(self, text: str, force: bool = False):
        if not self.on_status:
            return
        now = time.time()
        # Throttle updates to avoid Telegram rate limits (at most once every 1.5s unless forced)
        if force or (now - self.last_status_time >= 1.5):
            self.last_status_time = now
            self.current_status_text = text
            try:
                res = self.on_status(text)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    def cancel(self):
        self._cancelled = True
        if self.process and self.process.returncode is None:
            try:
                self.process.send_signal(signal.SIGINT)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

    def _ensure_conversation(self):
        conv = self.session.get_active_conv()
        if conv is None:
            conv = session_manager.create_new_conversation(self.session.user_id, title="Новый диалог")
        return conv

    def _build_cmd(self, resume_id: Optional[str], allow_effort: bool = True) -> List[str]:
        cmd = [
            config.CLAUDE_BIN,
            "-p", self.prompt,
            "--output-format", "stream-json",
            "--verbose",
        ]

        if self.permission_mode:
            cmd.extend(["--permission-mode", self.permission_mode])
        else:
            cmd.extend(["--permission-mode", "bypassPermissions"])

        system_parts = [TELEGRAM_PROMPT]
        if self.session.mode == "review" and self.permission_mode != "plan":
            system_parts.append(REVIEW_MODE_PROMPT)
        cmd.extend(["--append-system-prompt", "\n\n".join(system_parts)])

        if resume_id:
            cmd.extend(["--resume", resume_id])
            if not self.persist_session:
                cmd.append("--fork-session")
        elif not self.persist_session:
            cmd.append("--no-session-persistence")

        if self.session.model:
            cmd.extend(["--model", self.session.model])

        if config.FALLBACK_MODEL and config.FALLBACK_MODEL != self.session.model:
            cmd.extend(["--fallback-model", config.FALLBACK_MODEL])

        if allow_effort and self.session.effort and is_effort_supported_for_model(self.session.model):
            cmd.extend(["--effort", self.session.effort])

        if config.MAX_BUDGET_USD:
            cmd.extend(["--max-budget-usd", config.MAX_BUDGET_USD])

        cmd.extend(config.CLAUDE_EXTRA_ARGS)
        cmd.extend(self.extra_flags)
        return cmd

    async def run(self) -> Dict[str, Any]:
        """
        Executes the claude CLI and returns the execution result.
        Handles stale sessions, unsupported --effort and quota exhaustion.
        """
        conv = self._ensure_conversation()
        resume_id = conv.claude_session_id

        result = await self._run_internal(conv, resume_id, allow_effort=True)
        err_msg = (result.get("error") or "").lower()

        # Session missing on disk (e.g. migrated from another agent, or deleted) -> start fresh
        if (
            result.get("status") == "ERROR"
            and resume_id
            and ("no conversation found" in err_msg or "session" in err_msg and "not found" in err_msg)
        ):
            logger.info(f"Claude session {resume_id} not found. Starting a fresh session.")
            if self.persist_session:
                conv.claude_session_id = None
                session_manager.save()
            result = await self._run_internal(conv, None, allow_effort=True)
            err_msg = (result.get("error") or "").lower()

        if result.get("status") == "ERROR" and "effort" in err_msg:
            logger.info(f"Model {self.session.model} rejected --effort. Retrying without it...")
            result = await self._run_internal(conv, conv.claude_session_id if self.persist_session else resume_id,
                                              allow_effort=False)

        # Quota / usage limit detection
        if result.get("status") == "ERROR" and result.get("error"):
            is_quota, _ = quota_manager.detect_quota_error(result["error"])
            if is_quota:
                est_delay = await quota_manager.register_quota_exceeded(
                    user_id=self.session.user_id,
                    chat_id=self.chat_id,
                    model=self.session.model,
                    conv_title=conv.title,
                    error_text=result["error"],
                )
                time_hint = f"~{int(est_delay)} сек." if est_delay < 120 else f"~{int(est_delay // 60)} мин."
                result["response"] = (
                    f"⏳ <b>Лимит использования исчерпан для модели:</b> <code>{html.escape(self.session.model)}</code>\n"
                    f"<i>(Примерное время сброса: {time_hint})</i>\n\n"
                    f"🔔 <b>Я автоматически пришлю сообщение в этот чат, как только лимит обнулится!</b>"
                )

        return result

    async def _run_internal(self, conv, resume_id: Optional[str], allow_effort: bool = True) -> Dict[str, Any]:
        cmd = self._build_cmd(resume_id, allow_effort=allow_effort)
        tools_used: List[str] = []
        collected_response = ""
        last_assistant_text = ""
        plan_text = ""
        session_id = resume_id or ""
        error_msg: Optional[str] = None
        status = "SUCCESS"
        cost_usd: Optional[float] = None
        stderr_chunks: List[bytes] = []

        await self._notify_status("🤖 <i>Думаю над ответом...</i>", force=True)

        async def _drain_stderr(stream):
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        stderr_task = None
        try:
            cwd = self.session.cwd if os.path.isdir(self.session.cwd) else config.DEFAULT_CWD
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                limit=STREAM_LIMIT,
            )
            stderr_task = asyncio.create_task(_drain_stderr(self.process.stderr))

            while True:
                if self._cancelled:
                    break

                line = await self.process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                etype = data.get("type")

                if etype == "system":
                    subtype = data.get("subtype")
                    if subtype == "init":
                        sid = data.get("session_id")
                        if sid:
                            session_id = sid
                            if self.persist_session and conv.claude_session_id != sid:
                                conv.claude_session_id = sid
                                session_manager.save()
                    elif subtype == "api_retry":
                        await self._notify_status("🔁 <i>API временно недоступно, повторяю запрос...</i>")
                    elif subtype == "compact_boundary":
                        await self._notify_status("🗜️ <i>Сжимаю контекст диалога...</i>")

                elif etype == "assistant":
                    message = data.get("message") or {}
                    # Ignore subagent internals for the main response text
                    is_subagent = bool(data.get("parent_tool_use_id"))
                    for block in message.get("content") or []:
                        btype = block.get("type")
                        if btype == "text" and not is_subagent:
                            text = block.get("text") or ""
                            if text.strip():
                                last_assistant_text = text
                        elif btype == "tool_use":
                            tool_name = block.get("name") or "tool"
                            params = block.get("input") or {}
                            if tool_name == "ExitPlanMode" and params.get("plan"):
                                plan_text = str(params.get("plan"))
                            if tool_name not in tools_used:
                                tools_used.append(tool_name)
                            await self._notify_status(describe_tool(tool_name, params))
                        elif btype == "thinking" and not is_subagent:
                            await self._notify_status("💭 <i>Размышляю...</i>")

                elif etype == "result":
                    sid = data.get("session_id")
                    if sid:
                        session_id = sid
                        if self.persist_session and conv.claude_session_id != sid:
                            conv.claude_session_id = sid
                            session_manager.save()
                    cost_usd = data.get("total_cost_usd")
                    res_text = data.get("result")
                    if isinstance(res_text, str) and res_text.strip():
                        collected_response = res_text
                    if data.get("is_error") or (data.get("subtype") not in (None, "success")):
                        status = "ERROR"
                        errors = data.get("errors")
                        if isinstance(errors, list) and errors:
                            error_msg = "; ".join(str(e) for e in errors)
                        else:
                            error_msg = (res_text if isinstance(res_text, str) and res_text else None) \
                                or f"Claude Code завершился с ошибкой ({data.get('subtype')})"

            if self._cancelled:
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.process.kill()
                return {
                    "status": "CANCELLED",
                    "response": "⚠️ Операция отменена пользователем.",
                    "conversation_id": conv.id,
                    "session_id": session_id,
                    "error": "Cancelled",
                    "tools_used": tools_used,
                    "cost_usd": cost_usd,
                }

            await self.process.wait()
            if stderr_task:
                await stderr_task
            stderr_str = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()

            if self.process.returncode != 0 and status != "ERROR":
                status = "ERROR"
                error_msg = stderr_str or f"claude завершился с кодом {self.process.returncode}"
            elif status == "ERROR" and stderr_str and stderr_str not in (error_msg or ""):
                error_msg = f"{error_msg}\n{stderr_str}" if error_msg else stderr_str

        except FileNotFoundError:
            status = "ERROR"
            error_msg = (
                f"Не найден исполняемый файл Claude Code: {config.CLAUDE_BIN}. "
                f"Установите его (npm install -g @anthropic-ai/claude-code) или укажите CLAUDE_BIN_PATH в .env"
            )
        except asyncio.CancelledError:
            self.cancel()
            status = "CANCELLED"
            error_msg = "Task cancelled"
        except Exception as e:
            logger.error(f"Agent run failed: {e}", exc_info=True)
            status = "ERROR"
            error_msg = str(e)
        finally:
            if stderr_task and not stderr_task.done():
                stderr_task.cancel()

        if cost_usd is not None:
            logger.info(f"Claude turn finished: status={status}, cost=${cost_usd:.4f}, tools={tools_used}")

        if plan_text and status != "CANCELLED":
            # In plan mode the plan is delivered via the ExitPlanMode tool, and the run
            # may end with a "permission denied" style result — the plan is still valid.
            collected_response = plan_text
            status, error_msg = "SUCCESS", None
        elif status == "ERROR":
            collected_response = ""
        elif not collected_response:
            collected_response = last_assistant_text

        if not collected_response:
            if error_msg:
                collected_response = f"❌ <b>Ошибка выполнения:</b>\n<code>{html.escape(error_msg[:3000])}</code>"
            elif tools_used:
                tools_str = html.escape(", ".join(tools_used))
                collected_response = f"✅ <b>Действие успешно выполнено.</b>\n<i>(Использованы инструменты: {tools_str})</i>"
            else:
                collected_response = "ℹ️ <i>Агент завершил работу, но не сформировал текстового ответа.</i>"

        return {
            "status": status,
            "response": collected_response,
            "conversation_id": conv.id,
            "session_id": session_id,
            "error": error_msg,
            "tools_used": tools_used,
            "cost_usd": cost_usd,
        }
