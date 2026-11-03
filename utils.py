import re
import html
import os
import psutil
import time
import logging
from typing import List, Tuple, Optional
from pathlib import Path
from aiogram import Bot, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger("ClaudeBot.Utils")

# Record bot start time
BOT_START_TIME = time.time()

def get_persistent_keyboard(chat_title: str = "Новый диалог") -> ReplyKeyboardMarkup:
    """
    Returns a persistent bottom keyboard indicating the current active chat
    with quick action buttons.
    """
    clean_title = chat_title.strip()
    if len(clean_title) > 20:
        clean_title = clean_title[:18] + ".."
    if not clean_title:
        clean_title = "Новый диалог"

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=f"💬 {clean_title}"),
            ],
            [
                KeyboardButton(text="🌲 Файлы /tree"),
                KeyboardButton(text="📊 Статус"),
                KeyboardButton(text="⚙️ Меню"),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def get_response_inline_keyboard(is_review_mode: bool = True) -> InlineKeyboardMarkup:
    """
    Returns interactive inline action buttons under agent responses.
    In review mode: adds [✅ Да, выполняй] and [❌ Отменить] buttons.
    """
    if is_review_mode:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, выполняй", callback_data="confirm_act:yes"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_act:no"),
            ],
            [
                InlineKeyboardButton(text="🌲 Файлы /tree", callback_data="btn_tree"),
                InlineKeyboardButton(text="💬 Мои чаты", callback_data="btn_chats"),
            ]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🌲 Файлы /tree", callback_data="btn_tree"),
                InlineKeyboardButton(text="📊 Статус", callback_data="btn_status"),
                InlineKeyboardButton(text="💬 Мои чаты", callback_data="btn_chats"),
            ]
        ])


def get_chat_badge(conv_title: str, cwd: str) -> str:
    """
    Returns a formatted header badge indicating the active chat context and working directory.
    """
    clean_title = conv_title.strip() or "Диалог"
    short_cwd = cwd if len(cwd) <= 25 else "..." + cwd[-22:]
    return f"💬 <b>[{html.escape(clean_title)}]</b> <i>({html.escape(short_cwd)})</i>\n──────────────\n"


def sanitize_telegram_html(text: str) -> str:
    """
    Ensures only Telegram-supported HTML tags remain in the text,
    and escapes any unsupported raw HTML tags output by models.
    Telegram supported tags: b, strong, i, em, u, ins, s, strike, del, span, tg-spoiler, a, code, pre, blockquote, tg-emoji.
    """
    allowed_tags = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span", "tg-spoiler", "a", "code", "pre", "blockquote", "tg-emoji"}
    
    def tag_replacer(match):
        is_closing = bool(match.group(1))
        tag_name = match.group(2).lower()
        tag_attrs = match.group(3) or ""
        
        if tag_name in allowed_tags:
            if is_closing:
                return f"</{tag_name}>"
            else:
                return f"<{tag_name}{tag_attrs}>"
        else:
            return html.escape(match.group(0))

    return re.sub(r'<(/)?([a-zA-Z0-9_\-]+)([^>]*)>', tag_replacer, text)


def balance_html_tags(text: str) -> str:
    """
    Finds unclosed supported HTML tags and closes them at the end of the text.
    Also handles proper tag nesting.
    """
    supported_paired = ["pre", "code", "blockquote", "b", "strong", "i", "em", "u", "s", "a", "tg-spoiler"]
    tag_stack = []
    
    tokens = re.finditer(r'<(/)?([a-zA-Z0-9_\-]+)([^>]*)>', text)
    for t in tokens:
        is_closing = bool(t.group(1))
        tag_name = t.group(2).lower()
        if tag_name in supported_paired:
            if not is_closing:
                tag_stack.append(tag_name)
            else:
                if tag_stack and tag_stack[-1] == tag_name:
                    tag_stack.pop()
                elif tag_name in tag_stack:
                    while tag_stack and tag_stack[-1] != tag_name:
                        tag_stack.pop()
                    if tag_stack:
                        tag_stack.pop()

    result = text
    while tag_stack:
        unclosed = tag_stack.pop()
        result += f"</{unclosed}>"
        
    return result


def render_latex_to_image(latex_expr: str, output_dir: str = "/tmp") -> Optional[str]:
    """
    Renders a LaTeX expression to a PNG image using matplotlib.
    Returns the file path to the generated image, or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import uuid

        fig, ax = plt.subplots(figsize=(0.1, 0.1))
        ax.axis("off")
        fig.patch.set_facecolor("white")

        # Render LaTeX text centered
        ax.text(
            0.5, 0.5,
            f"${latex_expr}$",
            fontsize=18,
            ha="center", va="center",
            transform=ax.transAxes,
            color="black"
        )

        filepath = os.path.join(output_dir, f"latex_{uuid.uuid4().hex[:10]}.png")
        fig.savefig(filepath, dpi=200, bbox_inches="tight", pad_inches=0.15, facecolor="white")
        plt.close(fig)
        return filepath
    except Exception as e:
        logger.warning(f"Failed to render LaTeX: {e}")
        return None


# Unicode superscript/subscript maps for simple inline LaTeX
_SUPERSCRIPT_MAP = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵉʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛˣ")
_SUBSCRIPT_MAP = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")

# Common LaTeX symbols → Unicode
_LATEX_SYMBOLS = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\zeta": "ζ", r"\eta": "η", r"\theta": "θ",
    r"\iota": "ι", r"\kappa": "κ", r"\lambda": "λ", r"\mu": "μ",
    r"\nu": "ν", r"\xi": "ξ", r"\pi": "π", r"\rho": "ρ",
    r"\sigma": "σ", r"\tau": "τ", r"\phi": "φ", r"\chi": "χ",
    r"\psi": "ψ", r"\omega": "ω",
    r"\Alpha": "Α", r"\Beta": "Β", r"\Gamma": "Γ", r"\Delta": "Δ",
    r"\Theta": "Θ", r"\Lambda": "Λ", r"\Pi": "Π", r"\Sigma": "Σ",
    r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
    r"\infty": "∞", r"\pm": "±", r"\mp": "∓", r"\times": "×",
    r"\div": "÷", r"\cdot": "·", r"\leq": "≤", r"\geq": "≥",
    r"\neq": "≠", r"\approx": "≈", r"\equiv": "≡", r"\propto": "∝",
    r"\sum": "∑", r"\prod": "∏", r"\int": "∫", r"\partial": "∂",
    r"\nabla": "∇", r"\forall": "∀", r"\exists": "∃", r"\in": "∈",
    r"\notin": "∉", r"\subset": "⊂", r"\supset": "⊃", r"\cup": "∪",
    r"\cap": "∩", r"\emptyset": "∅", r"\to": "→", r"\rightarrow": "→",
    r"\leftarrow": "←", r"\Rightarrow": "⇒", r"\Leftarrow": "⇐",
    r"\iff": "⇔", r"\sqrt": "√", r"\langle": "⟨", r"\rangle": "⟩",
    r"\hbar": "ℏ", r"\ell": "ℓ", r"\Re": "ℜ", r"\Im": "ℑ",
}


def latex_to_unicode(expr: str) -> str:
    """
    Converts simple inline LaTeX expressions to Unicode approximation.
    For complex formulas, returns None (caller should fall back to image rendering).
    """
    result = expr.strip()

    # Replace known symbols
    for latex_cmd, uni_char in _LATEX_SYMBOLS.items():
        result = result.replace(latex_cmd, uni_char)

    # \frac{a}{b} → a/b
    result = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1)/(\2)', result)

    # Simple superscript: x^{2} or x^2
    def replace_sup(m):
        base = m.group(1) if m.group(1) else ""
        exp_text = m.group(2)
        translated = exp_text.translate(_SUPERSCRIPT_MAP)
        return base + translated
    result = re.sub(r'(\w)?\^\{([^}]+)\}', replace_sup, result)
    result = re.sub(r'(\w)?\^(\w)', replace_sup, result)

    # Simple subscript: x_{i} or x_i
    def replace_sub(m):
        base = m.group(1) if m.group(1) else ""
        sub_text = m.group(2)
        translated = sub_text.translate(_SUBSCRIPT_MAP)
        return base + translated
    result = re.sub(r'(\w)?_\{([^}]+)\}', replace_sub, result)
    result = re.sub(r'(\w)?_(\w)', replace_sub, result)

    # \text{...} → just the text
    result = re.sub(r'\\text\{([^}]+)\}', r'\1', result)
    # \mathrm{...} → just the text
    result = re.sub(r'\\mathrm\{([^}]+)\}', r'\1', result)
    # \mathbf{...} → bold approximation
    result = re.sub(r'\\mathbf\{([^}]+)\}', r'\1', result)

    # Remove leftover braces
    result = result.replace("{", "").replace("}", "")
    # Remove leftover backslash commands we couldn't parse
    result = re.sub(r'\\[a-zA-Z]+', '', result)

    return result.strip()


def markdown_to_html(text: str) -> str:
    """
    Converts standard Markdown text (from Claude Code) into Telegram-compatible HTML.
    Safely escapes HTML entities while properly rendering code blocks, inline code,
    headers, bold, italics, strikethroughs, blockquotes, links, lists, tables, and LaTeX.
    """
    if not text:
        return ""

    # Auto-close code blocks if unclosed
    if text.count('```') % 2 != 0:
        text += '\n```'

    # ── 0. Extract LaTeX blocks BEFORE anything else ──
    # Block LaTeX: $$...$$ or \[...\]
    latex_blocks = {}
    def save_latex_block(match):
        expr = match.group(1).strip()
        key = f"XLATBLKX{len(latex_blocks)}XLATBLKX"
        latex_blocks[key] = expr
        return key
    text = re.sub(r'\$\$(.*?)\$\$', save_latex_block, text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]', save_latex_block, text, flags=re.DOTALL)

    # Inline LaTeX: $...$ (but not $$) or \(...\)
    latex_inlines = {}
    def save_latex_inline(match):
        expr = match.group(1).strip()
        key = f"XLATINLX{len(latex_inlines)}XLATINLX"
        latex_inlines[key] = expr
        return key
    text = re.sub(r'(?<!\$)\$([^\$\n]+?)\$(?!\$)', save_latex_inline, text)
    text = re.sub(r'\\\((.+?)\\\)', save_latex_inline, text)

    # ── 1. Placeholders for code blocks ──
    code_blocks = {}
    def save_code_block(match):
        lang = (match.group(1) or "").strip()
        code = match.group(2)
        escaped_code = html.escape(code)
        key = f"XCBX{len(code_blocks)}XCBX"
        if lang:
            tag = f'<pre><code class="language-{html.escape(lang)}">{escaped_code}</code></pre>'
        else:
            tag = f'<pre><code>{escaped_code}</code></pre>'
        code_blocks[key] = tag
        return key

    text = re.sub(r'```([a-zA-Z0-9_\-\+]*)\n?(.*?)```', save_code_block, text, flags=re.DOTALL)

    # ── 2. Placeholders for inline code ──
    inline_codes = {}
    def save_inline_code(match):
        code = match.group(1)
        escaped_code = html.escape(code)
        key = f"XINLX{len(inline_codes)}XINLX"
        inline_codes[key] = f'<code>{escaped_code}</code>'
        return key

    text = re.sub(r'`([^`\n]+)`', save_inline_code, text)

    # ── 3. Escape HTML in regular text ──
    text = html.escape(text)

    # ── 4. Markdown Headers ──
    def replace_headers(match):
        header_text = match.group(2).strip()
        return f"\n<b>{header_text}</b>\n"
    text = re.sub(r'^(#{1,6})\s+(.+)$', replace_headers, text, flags=re.MULTILINE)

    # ── 5. Bold ──
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'(?<!\w)__(.+?)__(?!\w)', r'<b>\1</b>', text, flags=re.DOTALL)

    # ── 6. Italic ──
    text = re.sub(r'(?<!\w)\*([^\*\n]+?)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_([^_\n]+?)_(?!\w)', r'<i>\1</i>', text)

    # ── 7. Strikethrough ──
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text, flags=re.DOTALL)

    # ── 8. Blockquotes ──
    def replace_blockquote(match):
        quote_text = match.group(1).strip()
        return f"<blockquote>{quote_text}</blockquote>"
    text = re.sub(r'^(?:&gt;|>)\s*(.+)$', replace_blockquote, text, flags=re.MULTILINE)

    # ── 9. Lists (unordered and ordered) ──
    def replace_lists(text: str) -> str:
        lines = text.split('\n')
        result_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Unordered list: - item or * item (but not --- horizontal rule)
            ul_match = re.match(r'^(\s*)[-*]\s+(.+)$', line)
            # Ordered list: 1. item
            ol_match = re.match(r'^(\s*)\d+[.)]\s+(.+)$', line)

            if ul_match:
                content = ul_match.group(2)
                result_lines.append(f"  • {content}")
            elif ol_match:
                content = ol_match.group(2)
                # Find the ordinal number
                num_match = re.match(r'^(\s*)(\d+)[.)]\s+', line)
                num = num_match.group(2) if num_match else "•"
                result_lines.append(f"  {num}. {content}")
            else:
                result_lines.append(line)
            i += 1
        return '\n'.join(result_lines)

    text = replace_lists(text)

    # ── 10. Tables ──
    def replace_tables(text: str) -> str:
        lines = text.split('\n')
        result_lines = []
        i = 0
        while i < len(lines):
            # Detect table row: | col | col |
            if re.match(r'^\s*\|.+\|', lines[i]):
                table_lines = []
                while i < len(lines) and re.match(r'^\s*\|.+\|', lines[i]):
                    table_lines.append(lines[i])
                    i += 1

                # Parse table
                rows = []
                for tl in table_lines:
                    # Skip separator rows (|---|---| or |:---:|:---:|)
                    stripped = tl.strip()
                    cells_raw = stripped.strip('|').split('|')
                    if all(re.match(r'^[\s\-:]+$', c) for c in cells_raw):
                        continue
                    cells = [c.strip() for c in tl.strip().strip('|').split('|')]
                    rows.append(cells)

                if rows:
                    # First row is header
                    header = rows[0]
                    result_lines.append(f"<b>{'  │  '.join(header)}</b>")
                    result_lines.append("─" * min(40, max(10, sum(len(c) + 5 for c in header))))
                    for row in rows[1:]:
                        result_lines.append(f"{'  │  '.join(row)}")
                    result_lines.append("")  # blank line after table
            else:
                result_lines.append(lines[i])
                i += 1
        return '\n'.join(result_lines)

    text = replace_tables(text)

    # ── 11. Links ──
    def replace_link(match):
        label = match.group(1)
        url = match.group(2)
        if url.startswith("file://"):
            filepath = url.replace("file://", "")
            return f'<b>{label}</b> (<code>{filepath}</code>)'
        url_unescaped = html.unescape(url)
        return f'<a href="{url_unescaped}">{label}</a>'

    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', replace_link, text)

    # ── 12. Horizontal rules ──
    text = re.sub(r'^\s*([*\-_]){3,}\s*$', '──────────────', text, flags=re.MULTILINE)

    # ── 13. Restore inline code and code blocks ──
    for key, tag in inline_codes.items():
        text = text.replace(key, tag)
    for key, tag in code_blocks.items():
        text = text.replace(key, tag)

    # ── 14. Restore inline LaTeX → Unicode ──
    for key, expr in latex_inlines.items():
        uni = latex_to_unicode(expr)
        text = text.replace(key, f"<code>{html.escape(uni)}</code>")

    # ── 15. Restore block LaTeX → Unicode (with hint) ──
    # Block formulas: try Unicode first, mark with 📐 prefix
    for key, expr in latex_blocks.items():
        uni = latex_to_unicode(expr)
        text = text.replace(key, f"\n<pre>📐 {html.escape(uni)}</pre>\n")

    # ── 16. Sanitize and balance tags ──
    text = sanitize_telegram_html(text)
    text = balance_html_tags(text)

    return text.strip()


def split_message(text: str, max_length: int = 3800) -> List[str]:
    """
    Splits text into chunks of at most `max_length`, ensuring HTML tags
    are not broken across chunks.
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

        chunk_raw = remaining[:split_idx].strip()
        remaining = remaining[split_idx:].strip()

        chunk_balanced = balance_html_tags(chunk_raw)
        chunks.append(chunk_balanced)

    if remaining:
        chunks.append(balance_html_tags(remaining))

    return chunks


async def safe_send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup=None,
    parse_mode: Optional[str] = "HTML"
) -> types.Message:
    """
    Safely sends a message in Telegram. If HTML parsing fails, fallbacks to plain text
    so the user never loses the message content.
    """
    if parse_mode == "HTML":
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except TelegramBadRequest as e:
            logger.warning(f"Telegram HTML parse error in safe_send_message: {e}. Falling back to plain text.")
            clean_text = re.sub(r'<[^>]+>', '', text)
            return await bot.send_message(
                chat_id=chat_id,
                text=clean_text,
                parse_mode=None,
                reply_markup=reply_markup
            )
    else:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )


async def safe_reply(
    message: types.Message,
    text: str,
    reply_markup=None,
    parse_mode: Optional[str] = "HTML"
) -> types.Message:
    """
    Safely replies to a message. If HTML parsing fails, fallbacks to plain text.
    """
    if parse_mode == "HTML":
        try:
            return await message.answer(
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except TelegramBadRequest as e:
            logger.warning(f"Telegram HTML parse error in safe_reply: {e}. Falling back to plain text.")
            clean_text = re.sub(r'<[^>]+>', '', text)
            return await message.answer(
                text=clean_text,
                parse_mode=None,
                reply_markup=reply_markup
            )
    else:
        return await message.answer(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )


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
        if p.exists() and p.is_file():
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
