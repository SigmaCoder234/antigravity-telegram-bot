import os
import html
from pathlib import Path
from aiogram import Router, types, F
from aiogram.types import FSInputFile

import re
import config
from session_manager import session_manager
from utils import (
    markdown_to_html,
    split_message,
    extract_media_files,
    get_persistent_keyboard,
    get_response_inline_keyboard,
    get_chat_badge,
    safe_reply,
    render_latex_to_image,
    send_agent_response,
    ResponseProgress,
    ACTIVE_DRAFTS,
)
from agent_runner import AgentRunner
from shell_runner import ShellRunner
from handlers.commands import cmd_chats, cmd_tree, cmd_status, cmd_start

router = Router()

@router.message(F.text)
async def handle_text_message(message: types.Message):
    user_id = message.from_user.id
    user_text = message.text.strip()
    session = session_manager.get_session(user_id)

    # 1. Handle Quick Action buttons from persistent bottom keyboard
    if user_text.startswith("💬"):
        await cmd_chats(message)
        return
    elif user_text == "🌲 Файлы /tree":
        from aiogram.filters import CommandObject
        await cmd_tree(message, CommandObject(prefix="/", command="tree", args=""))
        return
    elif user_text == "📊 Статус":
        await cmd_status(message)
        return
    elif user_text == "⚙️ Меню":
        await cmd_start(message)
        return

    # 2. Check if user is renaming a conversation
    if session.waiting_rename_conv_id:
        conv_id = session.waiting_rename_conv_id
        session.waiting_rename_conv_id = None
        if session_manager.rename_conversation(user_id, conv_id, user_text):
            await safe_reply(
                message,
                f"✅ <b>Диалог переименован:</b> «{html.escape(user_text)}»",
                reply_markup=get_persistent_keyboard(user_text)
            )
        else:
            await safe_reply(message, "❌ Не удалось переименовать диалог.")
        return

    # 3. Check if an active shell command is waiting for user input
    if session.active_runner and isinstance(session.active_runner, ShellRunner) and session.active_runner.is_waiting():
        session.active_runner.write_input(user_text)
        await safe_reply(message, f"✅ <b>Ввод передан в консоль:</b> <code>{html.escape(user_text)}</code>")
        return

    # 4. Check if an agent task is already running
    if session.active_runner:
        await safe_reply(
            message,
            "⏳ <b>Агент уже выполняет задачу.</b>\n"
            "Подождите завершения или отправьте <code>/stop</code> для отмены."
        )
        return

    # 5. Regular Agent Execution with active chat badge
    active_conv = session.get_active_conv()
    initial_title = active_conv.title if active_conv else "Новый диалог"

    progress = ResponseProgress(
        bot=message.bot,
        chat_id=message.chat.id,
        chat_type=message.chat.type,
        conv_title=initial_title,
        cwd=session.cwd,
        status_prefix_html=f"<i>[Чат: «{html.escape(initial_title)}»]</i>\n",
    )

    runner = AgentRunner(
        session=session,
        prompt=user_text,
        chat_id=message.chat.id,
        on_status=progress.on_status,
        on_partial=progress.on_partial if progress.use_draft else None,
    )
    progress.set_stop_callback(runner.cancel)
    session.active_runner = runner

    try:
        await progress.start()
        result = await runner.run()
        await progress.finish()
        resp_text = result.get("response", "") or "ℹ️ <i>Агент завершил работу, но не вернул текстового ответа.</i>"
        conv_id = result.get("conversation_id")
        
        # Record turn in conversation history
        session_manager.record_turn(user_id, user_text, conv_id)
        
        # Get updated conversation title
        updated_conv = session.get_active_conv()
        current_title = updated_conv.title if updated_conv else "Диалог"

        is_review = (session.mode == "review")
        inline_kb = get_response_inline_keyboard(is_review_mode=is_review)

        sent_rich = await send_agent_response(
            bot=message.bot,
            chat_id=message.chat.id,
            text=resp_text,
            conv_title=current_title,
            cwd=session.cwd,
            reply_markup=inline_kb,
            is_markdown=result.get("is_markdown", True),
        )

        # Rich messages render formulas natively; otherwise send block LaTeX as images
        latex_block_exprs = [] if sent_rich else re.findall(r'\$\$(.*?)\$\$', resp_text, flags=re.DOTALL)
        if not sent_rich:
            latex_block_exprs += re.findall(r'\\\[(.*?)\\\]', resp_text, flags=re.DOTALL)
        for latex_expr in latex_block_exprs:
            latex_expr = latex_expr.strip()
            if not latex_expr:
                continue
            img_path = render_latex_to_image(latex_expr)
            if img_path and os.path.exists(img_path):
                try:
                    inp = FSInputFile(img_path, filename="formula.png")
                    await message.answer_photo(
                        photo=inp,
                        caption=f"📐 <code>{html.escape(latex_expr[:80])}</code>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                finally:
                    try:
                        os.remove(img_path)
                    except Exception:
                        pass

        # Check if the agent referenced or generated media/artifacts
        media_files = extract_media_files(resp_text)
        for mpath, mtype in media_files:
            p = Path(mpath)
            if p.exists() and p.is_file():
                try:
                    inp = FSInputFile(str(p), filename=p.name)
                    if mtype == "image":
                        await message.answer_photo(photo=inp, caption=f"📸 <code>{html.escape(p.name)}</code>", parse_mode="HTML")
                    else:
                        await message.answer_document(document=inp, caption=f"📄 <code>{html.escape(p.name)}</code>", parse_mode="HTML")
                except Exception:
                    pass

    except Exception as e:
        await safe_reply(message, f"❌ <b>Ошибка:</b> <code>{html.escape(str(e))}</code>")
    finally:
        await progress.finish()
        session.active_runner = None


@router.stopped_message_generation()
async def handle_stopped_generation(event: types.MessageGenerationStopped):
    """The user pressed the stop button on a streamed draft: cancel the agent run."""
    entry = ACTIVE_DRAFTS.get(event.draft_id)
    if not entry:
        return
    chat_id, stop_callback = entry
    if event.chat.id != chat_id:
        return
    stop_callback()
