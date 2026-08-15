import asyncio
import json
import os
import signal
import time
from typing import Optional, Callable, Dict, Any, List
import config
from session_manager import UserSession, session_manager

class AgentRunner:
    def __init__(
        self,
        session: UserSession,
        prompt: str,
        on_status: Optional[Callable[[str], Any]] = None,
        extra_flags: Optional[List[str]] = None,
    ):
        self.session = session
        self.prompt = prompt
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
            except Exception as e:
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

    async def run(self) -> Dict[str, Any]:
        """
        Executes agy CLI with stream-json output and returns a dict with:
        {
            "status": "SUCCESS" | "ERROR" | "CANCELLED",
            "response": str,
            "conversation_id": str,
            "error": Optional[str],
            "tools_used": List[str],
        }
        """
        cmd = [
            config.AGY_BIN,
            "-p", self.prompt,
            "--output-format", "stream-json",
        ]

        if self.session.conversation_id:
            cmd.extend(["--conversation", self.session.conversation_id])
        
        if self.session.model:
            cmd.extend(["--model", self.session.model])

        if self.session.effort:
            cmd.extend(["--effort", self.session.effort])

        if self.session.mode == "auto":
            cmd.append("--dangerously-skip-permissions")

        if self.extra_flags:
            cmd.extend(self.extra_flags)

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
                        
                        tool_desc = tool_name
                        if tool_name == "run_command":
                            cmd_preview = str(params.get("CommandLine", ""))[:60]
                            tool_desc = f"💻 Выполняю команду: <code>{cmd_preview}</code>"
                        elif tool_name in ["view_file", "replace_file_content", "write_to_file"]:
                            path_preview = params.get("AbsolutePath") or params.get("TargetFile") or ""
                            tool_desc = f"📝 Работа с файлом: <code>{os.path.basename(str(path_preview))}</code>"
                        elif tool_name == "list_dir":
                            tool_desc = f"📂 Читаю каталог: <code>{params.get('DirectoryPath', '.')}</code>"
                        elif tool_name == "search_web":
                            tool_desc = f"🔍 Ищу в сети: <code>{str(params.get('query', ''))[:40]}</code>"
                        else:
                            tool_desc = f"⚙️ Инструмент: <b>{tool_name}</b>"

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

        if not collected_response and error_msg:
            collected_response = f"❌ <b>Ошибка выполнения:</b>\n<code>{error_msg}</code>"

        return {
            "status": status,
            "response": collected_response,
            "conversation_id": final_conversation_id,
            "error": error_msg,
            "tools_used": tools_used,
        }
