import re
import html
import os
import psutil
import time
from typing import List, Tuple
from pathlib import Path

# Record bot start time
BOT_START_TIME = time.time()

def markdown_to_html(text: str) -> str:
    """
    Converts standard Markdown text (from LLM/agy) into Telegram-compatible HTML.
    Safely escapes HTML entities while rendering code blocks, bold, italics, and links.
    """
    if not text:
        return ""

    # 1. Placeholders for code blocks to protect them during other formatting
    code_blocks = {}
    def save_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        escaped_code = html.escape(code)
        key = f"XXCODEBLOCKXX{len(code_blocks)}XX"
        if lang:
            tag = f'<pre><code class="language-{html.escape(lang)}">{escaped_code}</code></pre>'
        else:
            tag = f'<pre><code>{escaped_code}</code></pre>'
        code_blocks[key] = tag
        return key

    # Match ```lang ... ``` or ``` ... ```
    text = re.sub(r'```([a-zA-Z0-9_\-\+]*)\n?(.*?)```', save_code_block, text, flags=re.DOTALL)

    # 2. Placeholders for inline code
    inline_codes = {}
    def save_inline_code(match):
        code = match.group(1)
        escaped_code = html.escape(code)
        key = f"XXINLINECODEXX{len(inline_codes)}XX"
        inline_codes[key] = f'<code>{escaped_code}</code>'
        return key

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. Escape HTML in regular text
    text = html.escape(text)

    # 4. Bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'(?<!\w)__(.+?)__(?!\w)', r'<b>\1</b>', text, flags=re.DOTALL)

    # 5. Italic: *text* or _text_
    text = re.sub(r'(?<!\w)\*([^\*]+?)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_([^_]+?)_(?!\w)', r'<i>\1</i>', text)

    # 6. Links: [text](url) -> <a href="url">text</a>
    def replace_link(match):
        label = match.group(1)
        url = match.group(2)
        # If url is file:/// link, keep it clean
        if url.startswith("file://"):
            filepath = url.replace("file://", "")
            return f'<b>{label}</b> (<code>{filepath}</code>)'
        # Unescape URL if it got escaped
        url_unescaped = html.unescape(url)
        return f'<a href="{url_unescaped}">{label}</a>'

    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', replace_link, text)

    # 7. Restore inline code and code blocks
    for key, tag in inline_codes.items():
        text = text.replace(key, tag)

    for key, tag in code_blocks.items():
        text = text.replace(key, tag)

    return text


def split_message(text: str, max_length: int = 3800) -> List[str]:
    """
    Splits text into chunks of at most `max_length`, trying to break on newlines or spaces.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_length:
        split_idx = remaining.rfind('\n\n', 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind('\n', 0, max_length)
        if split_idx == -1 or split_idx < max_length // 2:
            split_idx = remaining.rfind(' ', 0, max_length)
        if split_idx == -1:
            split_idx = max_length

        chunks.append(remaining[:split_idx].strip())
        remaining = remaining[split_idx:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def extract_media_files(text: str) -> List[Tuple[str, str]]:
    """
    Scans response text for referenced files and images (e.g. .png, .jpg, .svg, .pdf, .mp4).
    Returns list of (filepath, type) where type is 'image' or 'document'.
    """
    found = []
    path_regex = r'(?:file://)?(/[a-zA-Z0-9_\-\./]+\.(?:png|jpg|jpeg|gif|webp|svg|pdf|mp4|txt|zip|tar\.gz|json|py|sh|html|css|js))'
    matches = re.findall(path_regex, text, flags=re.IGNORECASE)
    
    seen = set()
    for raw_path in matches:
        clean_path = raw_path.strip().rstrip(").,'\"")
        if clean_path in seen:
            continue
        seen.add(clean_path)
        
        p = Path(clean_path)
        if p.is_file() and p.exists():
            ext = p.suffix.lower()
            if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                found.append((str(p), "image"))
            else:
                found.append((str(p), "document"))
                
    return found


def get_system_info() -> dict:
    """Returns system utilization statistics."""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime_sec = int(time.time() - BOT_START_TIME)
    
    hours, rem = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    return {
        "cpu_percent": cpu_percent,
        "mem_used_mb": mem.used // (1024 * 1024),
        "mem_total_mb": mem.total // (1024 * 1024),
        "mem_percent": mem.percent,
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "disk_percent": disk.percent,
        "uptime": uptime_str,
    }
