import asyncio
import os
import pty
import re
import signal
import time
from typing import Optional, Callable, Any, Dict

PROMPT_PATTERNS = [
    re.compile(r'\[[yY]/[nN]\]', re.IGNORECASE),
    re.compile(r'\([yY]/[nN]\)', re.IGNORECASE),
    re.compile(r'\[yes/no\]', re.IGNORECASE),
    re.compile(r'\(yes/no\)', re.IGNORECASE),
    re.compile(r'do you want to continue', re.IGNORECASE),
    re.compile(r'continue\s*\?', re.IGNORECASE),
    re.compile(r'press\s+\[?enter\]?\s+to\s+continue', re.IGNORECASE),
    re.compile(r'password\s*:', re.IGNORECASE),
    re.compile(r'enter\s+choice', re.IGNORECASE),
    re.compile(r'\[y/n\]\s*:', re.IGNORECASE),
]

class ShellRunner:
    def __init__(
        self,
        command: str,
        cwd: str,
        on_output: Optional[Callable[[str], Any]] = None,
        on_prompt: Optional[Callable[[str], Any]] = None,
    ):
        self.command = command
        self.cwd = cwd
        self.on_output = on_output
        self.on_prompt = on_prompt
        
        self.master_fd: Optional[int] = None
        self.process: Optional[asyncio.subprocess.Process] = None
        self.pid: Optional[int] = None
        self.output_buffer: str = ""
        self._cancelled = False
        self._waiting_for_input = False
        self.last_output_time = 0.0

    def is_waiting(self) -> bool:
        return self._waiting_for_input

    def write_input(self, user_input: str):
        if self.master_fd is not None:
            try:
                data = (user_input + "\n").encode("utf-8")
                os.write(self.master_fd, data)
                self._waiting_for_input = False
            except Exception as e:
                print(f"[ShellRunner] Error writing input: {e}")

    def terminate(self):
        self._cancelled = True
        self._waiting_for_input = False
        if self.pid:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGKILL)
            except Exception:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except Exception:
                    pass

    async def _emit_output(self, force: bool = False):
        if not self.on_output:
            return
        now = time.time()
        if force or (now - self.last_output_time >= 1.5):
            self.last_output_time = now
            # Trim buffer for preview (keep last 3000 chars)
            preview = self.output_buffer[-3000:]
            try:
                res = self.on_output(preview)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    def _check_for_prompts(self, new_chunk: str) -> Optional[str]:
        # Check last 300 chars of output buffer for prompts
        tail = self.output_buffer[-300:]
        for pat in PROMPT_PATTERNS:
            if pat.search(tail):
                lines = [l.strip() for l in tail.splitlines() if l.strip()]
                return lines[-1] if lines else "Требуется подтверждение ввода"
        return None

    async def run(self) -> Dict[str, Any]:
        """
        Executes shell command in a PTY and streams output.
        """
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd

        try:
            # Create subprocess connected to PTY slave
            self.process = await asyncio.create_subprocess_shell(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.cwd,
                start_new_session=True,
            )
            self.pid = self.process.pid
            os.close(slave_fd)  # Close slave in parent process

            # Set master_fd non-blocking
            os.set_blocking(master_fd, False)

            loop = asyncio.get_event_loop()

            while self.process.returncode is None:
                if self._cancelled:
                    break

                try:
                    # Read available bytes asynchronously
                    data = await loop.run_in_executor(None, lambda: self._read_fd(master_fd))
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        # Strip ANSI escape sequences for cleaner output
                        clean_text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
                        clean_text = clean_text.replace('\r\n', '\n').replace('\r', '\n')
                        self.output_buffer += clean_text

                        await self._emit_output()

                        prompt = self._check_for_prompts(clean_text)
                        if prompt and not self._waiting_for_input:
                            self._waiting_for_input = True
                            if self.on_prompt:
                                res = self.on_prompt(prompt)
                                if asyncio.iscoroutine(res):
                                    await res

                    else:
                        # No data available, small sleep
                        await asyncio.sleep(0.1)

                except Exception:
                    await asyncio.sleep(0.1)

                if self.process.returncode is not None:
                    break

                # Poll process state
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass

            # Read any leftover output
            try:
                leftover = self._read_fd(master_fd)
                if leftover:
                    text = leftover.decode("utf-8", errors="replace")
                    clean_text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text).replace('\r\n', '\n')
                    self.output_buffer += clean_text
            except Exception:
                pass

            await self._emit_output(force=True)

            return {
                "returncode": self.process.returncode if not self._cancelled else -1,
                "output": self.output_buffer,
                "cancelled": self._cancelled,
            }

        finally:
            if self.master_fd is not None:
                try:
                    os.close(self.master_fd)
                except Exception:
                    pass
                self.master_fd = None

    def _read_fd(self, fd: int) -> bytes:
        try:
            return os.read(fd, 4096)
        except (BlockingIOError, OSError):
            return b""
