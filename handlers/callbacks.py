import os
import asyncio
from pathlib import Path
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

import config
from session_manager import session_manager
from utils import get_system_info, get_persistent_keyboard
from shell_runner import ShellRunner
from file_explorer import generate_ascii_tree, get_explorer_keyboard

router = Router()

def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Мои чаты (/chats)", callback_data="btn_chats"),
            InlineKeyboardButton(text="✨ Новый чат (/new)", callback_data="btn_new"),
        ],
        [
            InlineKeyboardButton(text="🌲 Древо файлов (/tree)", callback_data="btn_tree"),
            InlineKeyboardButton(text="📊 Статус (/status)", callback_data="btn_status"),
        ],
        [
            InlineKeyboardButton(text="🧠 Сменить модель", callback_data="btn_choose_model"),
            InlineKeyboardButton(text="⚡ Размышления", callback_data="btn_choose_effort"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Режим работы", callback_data="btn_choose_mode"),
            InlineKeyboardButton(text="❓ Помощь (/help)", callback_data="btn_help"),
        ]
    ])

def get_chats_keyboard(user_id: int) -> InlineKeyboardMarkup:
    session = session_manager.get_session(user_id)
    buttons = []
    
    convs = list(session.conversations.values())
    convs.sort(key=lambda c: c.updated_at, reverse=True)
    
    for c in convs[:8]:
        is_active = (c.id == session.active_conv_id)
        prefix = "🟢 " if is_active else "💬 "
        title_snippet = (c.title[:24] + "..") if len(c.title) > 24 else c.title
        count_str = f" ({c.message_count} сообщ.)" if c.message_count > 0 else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix}{title_snippet}{count_str}",
                callback_data=f"switch_chat:{c.id}"
            )
        ])
    
    control_row = [
        InlineKeyboardButton(text="➕ Новый диалог", callback_data="btn_new"),
    ]
    if session.active_conv_id:
        control_row.append(InlineKeyboardButton(text="✏️ Переименовать", callback_data="btn_rename_chat"))
        control_row.append(InlineKeyboardButton(text="🗑 Удалить", callback_data="btn_delete_chat"))
    buttons.append(control_row)
    
    buttons.append([
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="btn_main_menu")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "btn_main_menu")
async def cb_main_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    active_conv = session.get_active_conv()
    conv_title = active_conv.title if active_conv else "Новый диалог"
    
    text = (
        f"🤖 <b>Главное меню:</b>\n\n"
        f"• Активный диалог: <b>{conv_title}</b>\n"
        f"• Модель: <code>{session.model}</code> ({session.effort})\n"
        f"• Рабочая папка: <code>{session.cwd}</code>\n"
        f"• Режим: <code>{'Автопилот ⚡' if session.mode == 'auto' else 'Ручное подтверждение 🛡️'}</code>"
    )
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())


@router.callback_query(F.data == "btn_chats")
async def cb_chats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    active_conv = session.get_active_conv()
    active_title = active_conv.title if active_conv else "Нет активного диалога"

    text = (
        f"💬 <b>Управление диалогами (чатами):</b>\n\n"
        f"🟢 <b>Вы сейчас в чате:</b> «{active_title}»\n"
        f"📂 <b>Рабочая папка:</b> <code>{session.cwd}</code>\n\n"
        f"<i>Выберите другой диалог из списка ниже, чтобы переключиться на него, "
        f"или создайте новый:</i>"
    )
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_chats_keyboard(user_id))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=get_chats_keyboard(user_id))


@router.callback_query(F.data.startswith("switch_chat:"))
async def cb_switch_chat(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conv_id = callback.data.split("switch_chat:")[1]
    if session_manager.switch_conversation(user_id, conv_id):
        session = session_manager.get_session(user_id)
        conv = session.get_active_conv()
        title = conv.title if conv else "Диалог"
        await callback.answer(f"Переключено на '{title}'!")
        await cb_chats(callback)
        await callback.message.answer(
            f"🟢 <b>Активный чат изменен:</b> «{title}»\n"
            f"📂 <b>Рабочая папка:</b> <code>{session.cwd}</code>",
            parse_mode="HTML",
            reply_markup=get_persistent_keyboard(title)
        )
    else:
        await callback.answer("Диалог не найден.")


@router.callback_query(F.data == "btn_new")
async def cb_new(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conv = session_manager.create_new_conversation(user_id, title="Новый диалог")
    session = session_manager.get_session(user_id)
    await callback.answer("Создан новый диалог!")
    await callback.message.answer(
        f"✨ <b>Создан новый чистый диалог:</b> «{conv.title}»\n"
        f"📂 Рабочая папка: <code>{session.cwd}</code>\n"
        f"<i>Все ваши предыдущие чаты сохранены в <code>/chats</code>.</i>",
        parse_mode="HTML",
        reply_markup=get_persistent_keyboard("Новый диалог")
    )


@router.callback_query(F.data == "btn_delete_chat")
async def cb_delete_chat(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    if session.active_conv_id:
        session_manager.delete_conversation(user_id, session.active_conv_id)
        await callback.answer("Диалог удален.")
        active_conv = session.get_active_conv()
        title = active_conv.title if active_conv else "Новый диалог"
        await cb_chats(callback)
        await callback.message.answer(
            f"🗑 <b>Диалог удален.</b>\nТекущий активный чат: «{title}»",
            parse_mode="HTML",
            reply_markup=get_persistent_keyboard(title)
        )
    else:
        await callback.answer("Нет активного диалога.")


@router.callback_query(F.data == "btn_rename_chat")
async def cb_rename_chat(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    if session.active_conv_id:
        session.waiting_rename_conv_id = session.active_conv_id
        await callback.answer()
        await callback.message.answer(
            "✏️ <b>Введите новое название для текущего диалога:</b>",
            parse_mode="HTML"
        )
    else:
        await callback.answer("Нет активного диалога.")


@router.callback_query(F.data == "btn_tree")
async def cb_tree(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    target_dir = Path(session.cwd).resolve()
    
    tree_text = generate_ascii_tree(target_dir, max_depth=2, max_entries=12)
    keyboard = get_explorer_keyboard(target_dir, current_cwd=session.cwd, page=0)
    
    escaped_tree = tree_text.replace("<", "&lt;").replace(">", "&gt;")
    text = (
        f"🌲 <b>Файловая система сервера:</b>\n"
        f"📍 Каталог: <code>{target_dir}</code>\n\n"
        f"<pre><code>{escaped_tree}</code></pre>\n"
        f"<i>Нажмите на папку для перехода внутрь или сделайте ее рабочей (CWD):</i>"
    )
    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("tree_cd:"))
async def cb_tree_cd(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    target_str = callback.data.split("tree_cd:")[1]
    target_dir = Path(target_str).resolve()
    
    if not target_dir.exists() or not target_dir.is_dir():
        await callback.answer("Каталог не найден.")
        return

    tree_text = generate_ascii_tree(target_dir, max_depth=2, max_entries=12)
    keyboard = get_explorer_keyboard(target_dir, current_cwd=session.cwd, page=0)
    
    escaped_tree = tree_text.replace("<", "&lt;").replace(">", "&gt;")
    text = (
        f"🌲 <b>Файловая система сервера:</b>\n"
        f"📍 Каталог: <code>{target_dir}</code>\n\n"
        f"<pre><code>{escaped_tree}</code></pre>\n"
        f"<i>Нажмите на папку для перехода внутрь или сделайте ее рабочей (CWD):</i>"
    )
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        pass


@router.callback_query(F.data.startswith("tree_page:"))
async def cb_tree_page(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    parts = callback.data.split("tree_page:")[1].rsplit(":", 1)
    target_dir = Path(parts[0]).resolve()
    page = int(parts[1])
    
    tree_text = generate_ascii_tree(target_dir, max_depth=2, max_entries=12)
    keyboard = get_explorer_keyboard(target_dir, current_cwd=session.cwd, page=page)
    
    escaped_tree = tree_text.replace("<", "&lt;").replace(">", "&gt;")
    text = (
        f"🌲 <b>Файловая система сервера:</b>\n"
        f"📍 Каталог: <code>{target_dir}</code>\n\n"
        f"<pre><code>{escaped_tree}</code></pre>\n"
        f"<i>Нажмите на папку для перехода внутрь или сделайте ее рабочей (CWD):</i>"
    )
    await callback.answer()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        pass


@router.callback_query(F.data.startswith("tree_refresh:"))
async def cb_tree_refresh(callback: types.CallbackQuery):
    await cb_tree_page(callback)


@router.callback_query(F.data.startswith("tree_set_cwd:"))
async def cb_tree_set_cwd(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_str = callback.data.split("tree_set_cwd:")[1]
    target_dir = Path(target_str).resolve()
    
    if session_manager.set_cwd(user_id, str(target_dir)):
        await callback.answer(f"Рабочий каталог изменен на {target_dir.name}!")
        session = session_manager.get_session(user_id)
        tree_text = generate_ascii_tree(target_dir, max_depth=2, max_entries=12)
        keyboard = get_explorer_keyboard(target_dir, current_cwd=session.cwd, page=0)
        escaped_tree = tree_text.replace("<", "&lt;").replace(">", "&gt;")
        text = (
            f"🌲 <b>Файловая система сервера:</b>\n"
            f"📍 <b>Рабочий каталог (CWD):</b> <code>{target_dir}</code> ✅\n\n"
            f"<pre><code>{escaped_tree}</code></pre>"
        )
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
    else:
        await callback.answer("Ошибка смены директории.")


@router.callback_query(F.data.startswith("tree_file:"))
async def cb_tree_file(callback: types.CallbackQuery):
    target_str = callback.data.split("tree_file:")[1]
    target_file = Path(target_str).resolve()
    
    if not target_file.exists() or not target_file.is_file():
        await callback.answer("Файл не найден.")
        return

    try:
        size = target_file.stat().st_size
        size_str = f"{size / (1024*1024):.2f} MB" if size > 1024*1024 else f"{size / 1024:.1f} KB"
    except Exception:
        size_str = "неизвестно"

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Скачать файл", callback_data=f"tree_dl:{target_file}"),
            InlineKeyboardButton(text="🔙 Назад к папке", callback_data=f"tree_cd:{target_file.parent}"),
        ]
    ])

    await callback.answer()
    await callback.message.answer(
        f"📄 <b>Файл:</b> <code>{target_file.name}</code>\n"
        f"📍 Путь: <code>{target_file}</code>\n"
        f"⚖️ Размер: <code>{size_str}</code>",
        parse_mode="HTML",
        reply_markup=markup
    )


@router.callback_query(F.data.startswith("tree_dl:"))
async def cb_tree_download(callback: types.CallbackQuery):
    target_str = callback.data.split("tree_dl:")[1]
    p = Path(target_str).resolve()
    
    if not p.exists() or not p.is_file():
        await callback.answer("Файл не найден.")
        return
        
    await callback.answer("Отправляю файл...")
    try:
        ext = p.suffix.lower()
        input_file = FSInputFile(str(p), filename=p.name)
        if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            await callback.message.answer_photo(photo=input_file, caption=f"📸 <code>{p.name}</code>", parse_mode="HTML")
        else:
            await callback.message.answer_document(document=input_file, caption=f"📄 <code>{p.name}</code>", parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка отправки: {e}")


@router.callback_query(F.data == "tree_close")
async def cb_tree_close(callback: types.CallbackQuery):
    await callback.answer("Закрыто.")
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "btn_status")
async def cb_status(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    sys_info = get_system_info()
    active_conv = session.get_active_conv()
    conv_title = active_conv.title if active_conv else "Новый диалог"
    
    active_op = "Отсутствует"
    if session.active_runner:
        active_op = "Выполняется задача ИИ 🤖"
    elif session.active_task and not session.active_task.done():
        active_op = "Выполняется фоновый процесс ⚙️"
        
    text = (
        f"📊 <b>Статус системы и агента:</b>\n\n"
        f"<b>🖥️ Сервер:</b>\n"
        f"• CPU: <code>{sys_info['cpu_percent']}%</code>\n"
        f"• RAM: <code>{sys_info['mem_used_mb']} MB / {sys_info['mem_total_mb']} MB ({sys_info['mem_percent']}%)</code>\n"
        f"• Диск: <code>{sys_info['disk_free_gb']} GB свободно / {sys_info['disk_total_gb']} GB ({sys_info['disk_percent']}%)</code>\n"
        f"• Аптайм бота: <code>{sys_info['uptime']}</code>\n\n"
        f"<b>🤖 Сессия агента:</b>\n"
        f"• Активный чат: <b>💬 {conv_title}</b> (всего: {len(session.conversations)})\n"
        f"• Активная операция: <b>{active_op}</b>\n"
        f"• Модель: <code>{session.model}</code> ({session.effort})\n"
        f"• Режим: <code>{session.mode}</code>\n"
        f"• Рабочий каталог: <code>{session.cwd}</code>\n"
        f"• Conversation ID: <code>{session.conversation_id or '—'}</code>"
    )
    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())


@router.callback_query(F.data == "btn_choose_model")
async def cb_choose_model(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    
    buttons = []
    for mid, mlabel in config.AVAILABLE_MODELS:
        prefix = "✅ " if session.model == mid else ""
        buttons.append([InlineKeyboardButton(text=f"{prefix}{mlabel}", callback_data=f"set_model:{mid}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.answer()
    await callback.message.answer(f"🧠 <b>Выберите модель ИИ:</b>", parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("set_model:"))
async def cb_set_model(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    model_id = callback.data.split("set_model:")[1]
    session_manager.set_model(user_id, model_id)
    await callback.answer(f"Модель изменена на {model_id}!")
    await callback.message.edit_text(f"✅ <b>Модель успешно изменена на:</b> <code>{model_id}</code>", parse_mode="HTML")


@router.callback_query(F.data == "btn_choose_effort")
async def cb_choose_effort(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    
    efforts = [
        ("low", "Low (Быстрый ответ) ⚡"),
        ("medium", "Medium (Сбалансированный) ⚖️"),
        ("high", "High (Глубокое размышление) 🧠"),
    ]
    buttons = []
    for eid, elabel in efforts:
        prefix = "✅ " if session.effort == eid else ""
        buttons.append([InlineKeyboardButton(text=f"{prefix}{elabel}", callback_data=f"set_effort:{eid}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.answer()
    await callback.message.answer(f"⚡ <b>Выберите уровень рассуждений:</b>", parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("set_effort:"))
async def cb_set_effort(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    effort_id = callback.data.split("set_effort:")[1]
    session_manager.set_effort(user_id, effort_id)
    await callback.answer(f"Уровень размышлений: {effort_id}!")
    await callback.message.edit_text(f"✅ <b>Уровень размышлений установлен на:</b> <code>{effort_id}</code>", parse_mode="HTML")


@router.callback_query(F.data == "btn_choose_mode")
async def cb_choose_mode(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    
    modes = [
        ("auto", "Автопилот ⚡ (без подтверждений)"),
        ("review", "Режим подтверждений 🛡️ (запрос подтверждения)"),
    ]
    buttons = []
    for mid, mlabel in modes:
        prefix = "✅ " if session.mode == mid else ""
        buttons.append([InlineKeyboardButton(text=f"{prefix}{mlabel}", callback_data=f"set_mode:{mid}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.answer()
    await callback.message.answer(f"⚙️ <b>Выберите режим работы агента:</b>", parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("set_mode:"))
async def cb_set_mode(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    mode_id = callback.data.split("set_mode:")[1]
    session_manager.set_mode(user_id, mode_id)
    mode_desc = "Автопилот ⚡" if mode_id == "auto" else "Режим подтверждений 🛡️"
    await callback.answer(f"Режим: {mode_desc}!")
    await callback.message.edit_text(f"✅ <b>Режим работы установлен на:</b> <b>{mode_desc}</b>", parse_mode="HTML")


@router.callback_query(F.data == "btn_help")
async def cb_help(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "💡 <b>Быстрые подсказки:</b>\n\n"
        "• <code>/chats</code> — список ваших диалогов с возможностью переключения.\n"
        "• <code>/tree</code> — древо файлов и интерактивная навигация по папкам.\n"
        "• <code>/exec npm run build</code> — запуск команды с кнопками подтверждения.\n"
        "• Отправьте любое фото или файл с подписью для анализа.\n"
        "• <code>/stop</code> — остановка текущей операции.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("shell_in:"))
async def cb_shell_input(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    val = callback.data.split("shell_in:")[1]
    input_str = "" if val == "enter" else val
    
    if session.active_runner and isinstance(session.active_runner, ShellRunner):
        session.active_runner.write_input(input_str)
        await callback.answer(f"Отправлено: '{input_str or 'Enter'}'")
        await callback.message.edit_text(
            f"✅ <b>Ввод передан в консоль:</b> <code>{input_str or 'Enter'}</code>",
            parse_mode="HTML"
        )
    else:
        await callback.answer("Процесс уже не ожидает ввода.")
        await callback.message.delete()


@router.callback_query(F.data == "shell_cancel")
async def cb_shell_cancel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = session_manager.get_session(user_id)
    if session.active_runner and isinstance(session.active_runner, ShellRunner):
        session.active_runner.terminate()
        await callback.answer("Процесс прерван!")
        await callback.message.edit_text("🛑 <b>Процесс был прерван по вашей команде.</b>", parse_mode="HTML")
    else:
        await callback.answer("Нет активного процесса.")
        await callback.message.delete()
