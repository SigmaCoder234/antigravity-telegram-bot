import os
import shutil
import asyncio
import html
import time
from pathlib import Path
from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

import config
from session_manager import session_manager
from utils import (
    markdown_to_html,
    split_message,
    get_system_info,
    get_persistent_keyboard,
    get_response_inline_keyboard,
    send_agent_response,
    get_chat_badge,
    safe_reply
)
from agent_runner import AgentRunner, is_effort_supported_for_model
from shell_runner import ShellRunner
from file_explorer import generate_ascii_tree, get_explorer_keyboard
from quota_manager import quota_manager

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
    
    # List conversations
    convs = list(session.conversations.values())
    convs.sort(key=lambda c: c.updated_at, reverse=True)
    
    for c in convs[:8]:
        is_active = (c.id == session.active_conv_id)
        prefix = "🟢 " if is_active else "💬 "
        active_tag = " (активен)" if is_active else ""
        title_snippet = (c.title[:20] + "..") if len(c.title) > 20 else c.title
        count_str = f" [{c.message_count}]" if c.message_count > 0 else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix}{title_snippet}{count_str}{active_tag}",
                callback_data=f"switch_chat:{c.id}"
            )
        ])
    
    # Control buttons
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


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    active_conv = session.get_active_conv()
    conv_title = active_conv.title if active_conv else "Новый диалог"
    
    effort_info = session.effort if is_effort_supported_for_model(session.model) else "авто"
    text = (
        f"👋 <b>Привет, {html.escape(message.from_user.full_name)}!</b>\n\n"
        f"Я твой персональный Telegram-мост к ИИ-агенту <b>Claude Code</b>.\n"
        f"Ты можешь отправлять мне задачи, файлы, фотографии и команды для выполнения на сервере.\n\n"
        f"📌 <b>Текущее окружение:</b>\n"
        f"• Активный чат: <b>💬 {html.escape(conv_title)}</b>\n"
        f"• Модель: <code>{html.escape(session.model)}</code>\n"
        f"• Уровень размышлений: <code>{html.escape(effort_info)}</code>\n"
        f"• Рабочая папка: <code>{html.escape(session.cwd)}</code>\n"
        f"• Режим: <code>{'Автопилот ⚡' if session.mode == 'auto' else 'Ручное подтверждение 🛡️'}</code>\n\n"
        f"💡 <i>Внизу экрана закреплена кнопка с названием вашего текущего чата!</i>"
    )
    # Send persistent keyboard first to attach to the bottom
    await safe_reply(
        message,
        text,
        reply_markup=get_persistent_keyboard(conv_title)
    )
    await safe_reply(message, "⚙️ <b>Панель управления:</b>", reply_markup=get_main_keyboard())


@router.message(Command("chats", "history"))
async def cmd_chats(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    active_conv = session.get_active_conv()
    active_title = active_conv.title if active_conv else "Нет активного диалога"

    text = (
        f"💬 <b>Управление диалогами (чатами):</b>\n\n"
        f"🟢 <b>Вы сейчас в чате:</b> «{html.escape(active_title)}»\n"
        f"📂 <b>Рабочая папка:</b> <code>{html.escape(session.cwd)}</code>\n\n"
        f"<i>Выберите другой диалог из списка ниже, чтобы переключить контекст, "
        f"или создайте новый:</i>"
    )
    await safe_reply(
        message,
        text,
        reply_markup=get_chats_keyboard(user_id)
    )


@router.message(Command("tree", "files"))
async def cmd_tree(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    arg = (command.args or "").strip()
    target_dir = Path(arg).resolve() if arg else Path(session.cwd)

    if not target_dir.exists() or not target_dir.is_dir():
        await safe_reply(message, f"❌ Директория не найдена: <code>{html.escape(str(target_dir))}</code>")
        return

    tree_text = generate_ascii_tree(target_dir, max_depth=2, max_entries=12)
    keyboard = get_explorer_keyboard(target_dir, current_cwd=session.cwd, page=0)

    escaped_tree = tree_text.replace("<", "&lt;").replace(">", "&gt;")
    text = (
        f"🌲 <b>Файловая система сервера:</b>\n"
        f"📍 Каталог: <code>{html.escape(str(target_dir))}</code>\n\n"
        f"<pre><code>{escaped_tree}</code></pre>\n"
        f"<i>Нажмите на папку ниже для перехода внутрь или сделайте ее рабочей:</i>"
    )
    await safe_reply(message, text, reply_markup=keyboard)


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📖 <b>Справочник команд и возможностей:</b>\n\n"
        "<b>🔹 Диалоги и контекст:</b>\n"
        "• <code>/chats</code> — Список и выбор ваших сохраненных диалогов\n"
        "• <code>/new</code> или <code>/reset</code> — Начать новый чистый диалог (сброс контекста)\n"
        "• <code>/btw &lt;вопрос&gt;</code> — Задать попутный быстрый вопрос (By-The-Way)\n"
        "• <code>/plan &lt;задача&gt;</code> — Запустить агента в режиме планирования задачи\n\n"
        "<b>🔹 Навигация по файлам и консоль:</b>\n"
        "• <code>/tree [папка]</code> — Интерактивное древо файлов и выбор рабочей папки кнопками\n"
        "• <code>/cd &lt;папка&gt;</code> — Сменить рабочую папку\n"
        "• <code>/pwd</code> — Показать текущую рабочую папку\n"
        "• <code>/ls [папка]</code> — Список файлов в папке\n"
        "• <code>/getfile &lt;путь&gt;</code> — Скачать файл с сервера в Telegram\n"
        "• <code>/exec &lt;команда&gt;</code> — Прямой запуск Bash с интерактивными кнопками [y/N]\n"
        "• <code>/status</code> — Нагрузка сервера (CPU, RAM, Диск) и статус агента\n"
        "• <code>/quota</code> — Статус квоты и проверка доступности\n"
        "• <code>/stop</code> — Прервать выполнение активной операции\n\n"
        "<b>🔹 Настройки агента:</b>\n"
        "• <code>/model</code> — Выбор языковой модели (Claude Opus, Sonnet, Haiku, Fable)\n"
        "• <code>/effort</code> — Глубина размышлений (Low … Max)\n"
        "• <code>/mode</code> — Автопилот / Ручное подтверждение"
    )
    await safe_reply(message, text)


@router.message(Command("new", "reset"))
async def cmd_new(message: types.Message):
    user_id = message.from_user.id
    conv = session_manager.create_new_conversation(user_id, title="Новый диалог")
    session = session_manager.get_session(user_id)
    await safe_reply(
        message,
        f"✨ <b>Создан новый чистый диалог:</b> «{html.escape(conv.title)}»\n"
        f"📂 Рабочая папка: <code>{html.escape(session.cwd)}</code>\n\n"
        f"<i>Все ваши предыдущие чаты сохранены в <code>/chats</code>.</i>",
        reply_markup=get_persistent_keyboard("Новый диалог")
    )


@router.message(Command("status"))
async def cmd_status(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    sys_info = get_system_info()
    active_conv = session.get_active_conv()
    conv_title = active_conv.title if active_conv else "Новая сессия"
    
    active_op = "Отсутствует"
    if session.active_runner:
        active_op = "Выполняется задача ИИ 🤖"
    elif session.active_task and not session.active_task.done():
        active_op = "Выполняется фоновый процесс ⚙️"

    quota_info = await quota_manager.get_quota_info(user_id, session.model)
    quota_status = "✅ В норме (доступна)"
    if quota_info:
        rem = max(0, int(quota_info["estimated_reset_at"] - time.time()))
        quota_status = f"⏳ Ожидание сброса (~{rem} сек.)"

    effort_str = session.effort if is_effort_supported_for_model(session.model) else f"{session.effort} (встроенный)"
        
    text = (
        f"📊 <b>Статус системы и агента:</b>\n\n"
        f"<b>🖥️ Сервер:</b>\n"
        f"• CPU: <code>{sys_info['cpu_percent']}%</code>\n"
        f"• RAM: <code>{sys_info['mem_used_mb']} MB / {sys_info['mem_total_mb']} MB ({sys_info['mem_percent']}%)</code>\n"
        f"• Диск: <code>{sys_info['disk_free_gb']} GB свободно / {sys_info['disk_total_gb']} GB ({sys_info['disk_percent']}%)</code>\n"
        f"• Аптайм бота: <code>{sys_info['uptime']}</code>\n\n"
        f"<b>🤖 Сессия агента:</b>\n"
        f"• Активный чат: <b>💬 {html.escape(conv_title)}</b> (всего: {len(session.conversations)})\n"
        f"• Активная операция: <b>{active_op}</b>\n"
        f"• Модель: <code>{html.escape(session.model)}</code> ({html.escape(effort_str)})\n"
        f"• Статус квоты: <b>{quota_status}</b>\n"
        f"• Режим: <code>{session.mode}</code>\n"
        f"• Рабочий каталог: <code>{html.escape(session.cwd)}</code>\n"
        f"• Claude Session ID: <code>{(active_conv.claude_session_id if active_conv else None) or '—'}</code>"
    )
    await safe_reply(message, text, reply_markup=get_main_keyboard())


@router.message(Command("quota"))
async def cmd_quota(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    
    quota_info = await quota_manager.get_quota_info(user_id, session.model)
    if quota_info:
        rem = max(0, int(quota_info["estimated_reset_at"] - time.time()))
        text = (
            f"⏳ <b>Статус квоты для модели {html.escape(session.model)}:</b>\n\n"
            f"Лимит запросов исчерпан. Ожидаем сброса квоты.\n"
            f"• Примерное время до проверки: <b>~{rem} сек.</b>\n"
            f"• Уведомление: <i>бот автоматически напишет вам сюда, как только квота станет доступна!</i>"
        )
    else:
        text = (
            f"✅ <b>Квота доступна!</b>\n\n"
            f"Модель: <code>{html.escape(session.model)}</code>\n"
            f"Ограничений по квоте не зафиксировано."
        )
    await safe_reply(message, text)


@router.message(Command("model"))
async def cmd_model(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    
    buttons = []
    for mid, mlabel in config.AVAILABLE_MODELS:
        prefix = "✅ " if session.model == mid else ""
        buttons.append([InlineKeyboardButton(text=f"{prefix}{mlabel}", callback_data=f"set_model:{mid}")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_reply(
        message,
        f"🧠 <b>Выберите модель ИИ</b> (сейчас: <code>{html.escape(session.model)}</code>):",
        reply_markup=markup
    )


@router.message(Command("effort"))
async def cmd_effort(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    
    supports_eff = is_effort_supported_for_model(session.model)
    note = "" if supports_eff else f"\n\n<i>⚠️ Для текущей модели <code>{html.escape(session.model)}</code> уровень размышлений зафиксирован.</i>"
    
    efforts = config.AVAILABLE_EFFORTS
    buttons = []
    for eid, elabel in efforts:
        prefix = "✅ " if session.effort == eid else ""
        buttons.append([InlineKeyboardButton(text=f"{prefix}{elabel}", callback_data=f"set_effort:{eid}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_reply(
        message,
        f"⚡ <b>Выберите уровень рассуждений:</b>{note}",
        reply_markup=markup
    )


@router.message(Command("mode"))
async def cmd_mode(message: types.Message):
    user_id = message.from_user.id
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
    await safe_reply(message, f"⚙️ <b>Режим исполнения действий агентом:</b>", reply_markup=markup)


@router.message(Command("pwd", "cwd"))
async def cmd_pwd(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    await safe_reply(message, f"📂 Текущий рабочий каталог: <code>{html.escape(session.cwd)}</code>")


@router.message(Command("cd"))
async def cmd_cd(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    arg = (command.args or "").strip()
    if not arg:
        await safe_reply(message, "⚠️ Укажите путь к папке: <code>/cd /путь/к/каталогу</code> или используйте <code>/tree</code>")
        return
    
    session = session_manager.get_session(user_id)
    target_path = Path(session.cwd) / arg if not arg.startswith("/") else Path(arg)
    target_path = target_path.resolve()
    
    if session_manager.set_cwd(user_id, str(target_path)):
        await safe_reply(message, f"✅ Рабочий каталог изменен на: <code>{html.escape(str(target_path))}</code>")
    else:
        await safe_reply(message, f"❌ Каталог не найден: <code>{html.escape(str(target_path))}</code>")


@router.message(Command("ls"))
async def cmd_ls(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    arg = (command.args or "").strip()
    target_dir = Path(arg).resolve() if arg else Path(session.cwd)
    
    if not target_dir.exists() or not target_dir.is_dir():
        await safe_reply(message, f"❌ Каталог не существует: <code>{html.escape(str(target_dir))}</code>")
        return
        
    try:
        entries = sorted(list(target_dir.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = [f"📂 <b>Каталог:</b> <code>{html.escape(str(target_dir))}</code>\n"]
        for entry in entries[:40]:
            if entry.is_dir():
                lines.append(f"📁 <code>{html.escape(entry.name)}/</code>")
            else:
                size_str = f"{entry.stat().st_size / 1024:.1f} KB" if entry.stat().st_size > 1024 else f"{entry.stat().st_size} B"
                lines.append(f"📄 <code>{html.escape(entry.name)}</code> ({size_str})")
        if len(entries) > 40:
            lines.append(f"\n<i>... и еще {len(entries) - 40} элементов</i>")
            
        await safe_reply(message, "\n".join(lines))
    except Exception as e:
        await safe_reply(message, f"❌ Ошибка чтения каталога: <code>{html.escape(str(e))}</code>")


@router.message(Command("getfile"))
async def cmd_getfile(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    arg = (command.args or "").strip()
    if not arg:
        await safe_reply(message, "⚠️ Укажите путь к файлу: <code>/getfile /путь/к/файлу</code>")
        return
        
    p = Path(session.cwd) / arg if not arg.startswith("/") else Path(arg)
    p = p.resolve()
    
    if not p.exists() or not p.is_file():
        await safe_reply(message, f"❌ Файл не найден: <code>{html.escape(str(p))}</code>")
        return
        
    try:
        ext = p.suffix.lower()
        input_file = FSInputFile(str(p), filename=p.name)
        if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            await message.answer_photo(photo=input_file, caption=f"📸 <code>{html.escape(p.name)}</code>", parse_mode="HTML")
        else:
            await message.answer_document(document=input_file, caption=f"📄 <code>{html.escape(p.name)}</code>", parse_mode="HTML")
    except Exception as e:
        await safe_reply(message, f"❌ Ошибка отправки файла: <code>{html.escape(str(e))}</code>")


@router.message(Command("stop", "cancel"))
async def cmd_stop(message: types.Message):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    
    stopped = False
    if session.active_runner:
        session.active_runner.cancel()
        stopped = True
    if session.active_task and not session.active_task.done():
        session.active_task.cancel()
        stopped = True
        
    if stopped:
        await safe_reply(message, "🛑 <b>Текущая операция прервана.</b>")
    else:
        await safe_reply(message, "ℹ️ Нет активных фоновых задач для остановки.")


@router.message(Command("btw"))
async def cmd_btw(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    arg = (command.args or "").strip()
    if not arg:
        await safe_reply(message, "⚠️ Укажите вопрос: <code>/btw ваш попутный вопрос</code>")
        return
        
    status_msg = await safe_reply(message, "💬 <i>Обрабатываю попутный вопрос...</i>")
    
    btw_prompt = f"[Попутный вопрос от пользователя (By-The-Way). Ответь кратко и четко]: {arg}"
    runner = AgentRunner(
        session=session,
        prompt=btw_prompt,
        chat_id=message.chat.id,
        persist_session=False,
    )
    session.active_runner = runner
    
    try:
        result = await runner.run()
        resp_text = result.get("response", "") or "ℹ️ <i>Агент завершил работу, но не сформировал ответа.</i>"

        try:
            await status_msg.delete()
        except Exception:
            pass
        conv = session.get_active_conv()
        await send_agent_response(
            bot=message.bot,
            chat_id=message.chat.id,
            text=resp_text,
            conv_title=conv.title if conv else "Диалог",
            cwd=session.cwd,
            is_markdown=result.get("is_markdown", True),
            header_md="💬 **Попутный ответ:**\n\n",
            header_html="💬 <b>Попутный ответ:</b>\n\n",
        )
    except Exception as e:
        await safe_reply(message, f"❌ Ошибка: {html.escape(str(e))}")
    finally:
        session.active_runner = None


@router.message(Command("plan"))
async def cmd_plan(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    arg = (command.args or "").strip()
    if not arg:
        await safe_reply(message, "⚠️ Укажите задачу для планирования: <code>/plan описание задачи</code>")
        return
        
    status_msg = await safe_reply(message, "📋 <i>Составляю план выполнения...</i>")
    
    async def update_status(text: str):
        try:
            await status_msg.edit_text(text, parse_mode="HTML")
        except Exception:
            pass

    plan_prompt = f"[Составь детальный и практический план реализации следующей задачи]: {arg}"
    runner = AgentRunner(
        session=session,
        prompt=plan_prompt,
        chat_id=message.chat.id,
        on_status=update_status,
        permission_mode="plan",
    )
    session.active_runner = runner
    
    try:
        result = await runner.run()
        resp_text = result.get("response", "") or "План не сформирован."

        try:
            await status_msg.delete()
        except Exception:
            pass

        conv = session.get_active_conv()
        await send_agent_response(
            bot=message.bot,
            chat_id=message.chat.id,
            text=resp_text,
            conv_title=conv.title if conv else "Диалог",
            cwd=session.cwd,
            is_markdown=result.get("is_markdown", True),
            header_md="📋 **План выполнения:**\n\n",
            header_html="📋 <b>План выполнения:</b>\n\n",
        )
    except Exception as e:
        await safe_reply(message, f"❌ Ошибка планирования: {html.escape(str(e))}")
    finally:
        session.active_runner = None


@router.message(Command("exec"))
async def cmd_exec(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    arg = (command.args or "").strip()
    if not arg:
        await safe_reply(message, "⚠️ Укажите команду: <code>/exec apt update</code> или <code>/exec ls -la</code>")
        return
        
    live_msg = await safe_reply(
        message,
        f"💻 <b>Запуск:</b> <code>{html.escape(arg)}</code>\n<i>Ожидание вывода...</i>"
    )

    async def update_output(preview_text: str):
        escaped = html.escape(preview_text)
        try:
            await live_msg.edit_text(
                f"💻 <b>Выполнение:</b> <code>{html.escape(arg)}</code>\n"
                f"<pre><code>{escaped}</code></pre>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    async def prompt_callback(prompt_text: str):
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes (y)", callback_data="shell_in:y"),
                InlineKeyboardButton(text="❌ No (n)", callback_data="shell_in:n"),
            ],
            [
                InlineKeyboardButton(text="⏎ Enter", callback_data="shell_in:enter"),
                InlineKeyboardButton(text="⏹ Прервать", callback_data="shell_cancel"),
            ]
        ])
        await safe_reply(
            message,
            f"⚠️ <b>Консоль запрашивает ввод:</b>\n<code>{html.escape(prompt_text)}</code>\n\n"
            f"<i>Нажмите кнопку ниже или отправьте нужный текст в чат:</i>",
            reply_markup=markup
        )

    runner = ShellRunner(
        command=arg,
        cwd=session.cwd,
        on_output=update_output,
        on_prompt=prompt_callback
    )
    session.active_runner = runner

    try:
        res = await runner.run()
        out = res.get("output", "")
        code = res.get("returncode", 0)
        cancelled = res.get("cancelled", False)
        
        status_str = "⏹ Прервано" if cancelled else ("✅ Завершено (код 0)" if code == 0 else f"⚠️ Код ошибки: {code}")
        
        escaped_out = html.escape(out[-3500:]) if out else "<i>(нет вывода)</i>"
        final_text = (
            f"💻 <b>Команда:</b> <code>{html.escape(arg)}</code>\n"
            f"<b>Статус:</b> {status_str}\n\n"
            f"<pre><code>{escaped_out}</code></pre>"
        )
        try:
            await live_msg.edit_text(final_text, parse_mode="HTML")
        except Exception:
            await safe_reply(message, final_text)

    except Exception as e:
        await safe_reply(message, f"❌ Ошибка запуска: {html.escape(str(e))}")
    finally:
        session.active_runner = None
