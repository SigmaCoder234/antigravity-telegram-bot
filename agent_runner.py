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

logger = logging.getLogger("AntigravityBot.AgentRunner")

def is_effort_supported_for_model(model_name: Optional[str]) -> bool:
    """
    Determines if the given model supports the --effort CLI flag in agy.
    Non-Gemini models (claude, gpt, deepseek, etc.) do NOT support --effort.
    """
    if not model_name:
        return False
    m_lower = model_name.lower()
    if any(prefix in m_lower for prefix in ["claude", "gpt", "o1", "o3", "deepseek", "qwen", "llama", "mistral"]):
        return False
    if "gemini" in m_lower:
        return True
    return False


class AgentRunner:
    def __init__(
        self,
        session: UserSession,
        prompt: str,
        chat_id: Optional[int] = None,
        on_status: Optional[Callable[[str], Any]] = None,
        extra_flags: Optional[List[str]] = None,
    ):
        self.session = session
        self.prompt = prompt
        self.chat_id = chat_id or session.user_id
        self.on_status = on_status
        self.extra_flags = extra_flags or []
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
        if self.process:
            try:
                self.process.send_signal(signal.SIGINT)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

    def _build_cmd(self, allow_effort: bool = True) -> List[str]:
        prompt_text = self.prompt
        if self.session.mode == "review" and "--mode" not in self.extra_flags:
            prompt_text = (
                "[РЕЖИМ С ПОДТВЕРЖДЕНИЯМИ]: "
                "Если для решения задачи требуется запуск bash-команд на сервере или изменение файлов, "
                "сначала обязательно опиши пользователю предлагаемые шаги/команды и спроси его согласие/подтверждение на их выполнение.\n\n"
                f"{self.prompt}"
            )

        cmd = [
            config.AGY_BIN,
            "-p", prompt_text,
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]

        if self.session.conversation_id:
            cmd.extend(["--conversation", self.session.conversation_id])
        
        if self.session.model:
            cmd.extend(["--model", self.session.model])

        if allow_effort and self.session.effort and is_effort_supported_for_model(self.session.model):
            cmd.extend(["--effort", self.session.effort])

        if self.extra_flags:
            cmd.extend(self.extra_flags)

        return cmd

    async def run(self) -> Dict[str, Any]:
        """
        Executes agy CLI with stream-json output and returns execution result.
        Automatically handles non-effort models and quota exhaustion tracking.
        """
        result = await self._run_internal(allow_effort=True)
        
        # Check if error is due to unsupported effort flag, and retry once without effort
        err_msg = result.get("error") or ""
        if result.get("status") == "ERROR" and "--effort is not supported" in err_msg:
            logger.info(f"Model {self.session.model} rejected --effort flag. Retrying without --effort...")
            result = await self._run_internal(allow_effort=False)

        # Check for quota exhaustion
        if result.get("status") == "ERROR" and result.get("error"):
            is_quota, est_sec = quota_manager.detect_quota_error(result["error"])
            if is_quota:
                conv = self.session.get_active_conv()
                conv_title = conv.title if conv else "Новый диалог"
                est_delay = await quota_manager.register_quota_exceeded(
                    user_id=self.session.user_id,
                    chat_id=self.chat_id,
                    model=self.session.model,
                    conv_title=conv_title,
                    error_text=result["error"]
                )
                time_hint = f"~{int(est_delay)} сек." if est_delay < 120 else f"~{int(est_delay // 60)} мин."
                quota_alert = (
                    f"⏳ <b>Лимит квоты исчерпан для модели:</b> <code>{html.escape(self.session.model)}</code>\n"
                    f"<i>(Примерное время сброса: {time_hint})</i>\n\n"
                    f"🔔 <b>Я автоматически пришлю сообщение в этот чат, как только квота обнулится!</b>"
                )
                result["response"] = quota_alert

        return result

    async def _run_internal(self, allow_effort: bool = True) -> Dict[str, Any]:
        cmd = self._build_cmd(allow_effort=allow_effort)
        tools_used = []
        collected_response = ""
        final_conversation_id = self.session.conversation_id or ""
        error_msg = None
        status = "SUCCESS"

        await self._notify_status("🤖 <i>Думаю над ответом...</i>", force=True)

        try:
            cwd = self.session.cwd if os.path.exists(self.session.cwd) else config.DEFAULT_CWD
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            # Read stdout line by line
            while True:
                if self._cancelled:
                    status = "CANCELLED"
                    return {
                        "status": "CANCELLED",
                        "response": "⚠️ Операция отменена пользователем.",
                        "conversation_id": final_conversation_id,
                        "error": "Cancelled",
                        "tools_used": tools_used,
                    }

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

                event_type = data.get("event")

                if event_type == "init":
                    conv_id = data.get("conversation_id")
                    if conv_id:
                        final_conversation_id = conv_id
                        self.session.conversation_id = conv_id
                        session_manager.save()

                elif event_type == "step_update":
                    step = data.get("step_update", {})
                    stype = step.get("step_type")
                    state = step.get("state")
                    tool_name = step.get("tool_name")
                    text_delta = step.get("text_delta")

                    if text_delta:
                        collected_response += text_delta

                    if stype == "tool" and state == "ACTIVE":
                        tool_info = step.get("tool_info", {})
                        params = tool_info.get("parameters", {})
                        
                        tool_desc = html.escape(str(tool_name))
                        if tool_name == "run_command":
                            cmd_preview = html.escape(str(params.get("CommandLine", ""))[:60])
                            tool_desc = f"💻 Выполняю команду: <code>{cmd_preview}</code>"
                        elif tool_name in ["view_file", "replace_file_content", "write_to_file"]:
                            path_preview = params.get("AbsolutePath") or params.get("TargetFile") or ""
                            base_name = html.escape(os.path.basename(str(path_preview)))
                            tool_desc = f"📝 Работа с файлом: <code>{base_name}</code>"
                        elif tool_name == "list_dir":
                            dir_path = html.escape(str(params.get('DirectoryPath', '.')))
                            tool_desc = f"📂 Читаю каталог: <code>{dir_path}</code>"
                        elif tool_name == "search_web":
                            query_str = html.escape(str(params.get('query', ''))[:40])
                            tool_desc = f"🔍 Ищу в сети: <code>{query_str}</code>"
                        else:
                            tool_desc = f"⚙️ Инструмент: <b>{html.escape(str(tool_name))}</b>"

                        if tool_name not in tools_used:
                            tools_used.append(tool_name)

                        await self._notify_status(tool_desc)

                elif event_type == "result":
                    res = data.get("result", {})
                    status = res.get("status", "SUCCESS")
                    resp = res.get("response", "")
                    if resp:
                        collected_response = resp
                    conv_id = res.get("conversation_id")
                    if conv_id:
                        final_conversation_id = conv_id
                        self.session.conversation_id = conv_id
                        session_manager.save()
                    if status == "ERROR":
                        error_msg = res.get("error") or "Неизвестная ошибка агента"

            await self.process.wait()

            if self.process.returncode != 0 and status != "ERROR":
                stderr_bytes = await self.process.stderr.read()
                stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()
                if stderr_str:
                    error_msg = stderr_str
                    status = "ERROR"

        except asyncio.CancelledError:
            self.cancel()
            status = "CANCELLED"
            error_msg = "Task cancelled"
        except Exception as e:
            status = "ERROR"
            error_msg = str(e)

        if not collected_response:
            if error_msg:
                collected_response = f"❌ <b>Ошибка выполнения:</b>\n<code>{html.escape(error_msg)}</code>"
            elif tools_used:
                tools_str = html.escape(", ".join(tools_used))
                collected_response = f"✅ <b>Действие успешно выполнено.</b>\n<i>(Использованы инструменты: {tools_str})</i>"
            else:
                collected_response = "ℹ️ <i>Агент завершил работу, но не сформировал текстового ответа.</i>"

        return {
            "status": status,
            "response": collected_response,
            "conversation_id": final_conversation_id,
            "error": error_msg,
            "tools_used": tools_used,
        }
