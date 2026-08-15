import os
import math
from pathlib import Path
from typing import Tuple, List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def generate_ascii_tree(root_path: Path, max_depth: int = 2, max_entries: int = 15) -> str:
    """
    Generates a clean ASCII tree representation of the filesystem hierarchy.
    """
    if not root_path.exists() or not root_path.is_dir():
        return f"{root_path} (директория не найдена)"

    lines = [f"📁 {root_path.name or str(root_path)}/"]

    def _walk(current_dir: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(list(current_dir.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}└── ⛔ [Доступ ограничен]")
            return
        except Exception:
            return

        total = len(entries)
        display_entries = entries[:max_entries]

        for i, entry in enumerate(display_entries):
            is_last = (i == len(display_entries) - 1) and (total <= max_entries)
            connector = "└── " if is_last else "├── "
            
            if entry.is_dir():
                lines.append(f"{prefix}{connector}📁 {entry.name}/")
                extension = "    " if is_last else "│   "
                _walk(entry, prefix + extension, depth + 1)
            else:
                try:
                    size = entry.stat().st_size
                    if size > 1024 * 1024:
                        size_str = f"{size / (1024*1024):.1f} MB"
                    elif size > 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size} B"
                except Exception:
                    size_str = ""
                size_suffix = f" ({size_str})" if size_str else ""
                lines.append(f"{prefix}{connector}📄 {entry.name}{size_suffix}")

        if total > max_entries:
            lines.append(f"{prefix}└── ... (+ еще {total - max_entries} файлов/папок)")

    _walk(root_path, "", 1)
    return "\n".join(lines)


def get_explorer_keyboard(target_path: Path, current_cwd: str, page: int = 0, page_size: int = 6) -> InlineKeyboardMarkup:
    """
    Builds an interactive navigation inline keyboard for browsing files and folders.
    """
    buttons = []

    # Row 1: Up button + Set CWD button
    parent_path = target_path.parent
    is_current_cwd = str(target_path.resolve()) == str(Path(current_cwd).resolve())

    top_row = []
    if parent_path and parent_path != target_path:
        top_row.append(InlineKeyboardButton(text="⬆️ Наверх (..)", callback_data=f"tree_cd:{parent_path}"))
    
    if is_current_cwd:
        top_row.append(InlineKeyboardButton(text="✅ Текущая CWD", callback_data="noop"))
    else:
        top_row.append(InlineKeyboardButton(text="📍 Сделать рабочей (CWD)", callback_data=f"tree_set_cwd:{target_path}"))
    
    buttons.append(top_row)

    # Get directory items
    try:
        entries = sorted(list(target_path.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
    except Exception:
        entries = []

    total_items = len(entries)
    total_pages = max(1, math.ceil(total_items / page_size))
    page = max(0, min(page, total_pages - 1))

    start_idx = page * page_size
    page_entries = entries[start_idx : start_idx + page_size]

    # Add buttons for folders and files
    for entry in page_entries:
        if entry.is_dir():
            buttons.append([
                InlineKeyboardButton(
                    text=f"📁 {entry.name}/",
                    callback_data=f"tree_cd:{entry}"
                )
            ])
        else:
            try:
                size = entry.stat().st_size
                size_str = f" ({size//1024} KB)" if size > 1024 else f" ({size} B)"
            except Exception:
                size_str = ""
            buttons.append([
                InlineKeyboardButton(
                    text=f"📄 {entry.name}{size_str}",
                    callback_data=f"tree_file:{entry}"
                )
            ])

    # Pagination buttons if needed
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"tree_page:{target_path}:{page-1}"))
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
            
        nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"tree_page:{target_path}:{page+1}"))
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
        buttons.append(nav_row)

    # Bottom utility row
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"tree_refresh:{target_path}:{page}"),
        InlineKeyboardButton(text="❌ Закрыть", callback_data="tree_close"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
