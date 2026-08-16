import os
import time
import html
from pathlib import Path
from aiogram import Router, types, F, Bot
from aiogram.types import FSInputFile

import config
from session_manager import session_manager
from utils import (
    markdown_to_html,
    split_message,
    extract_media_files,
    get_persistent_keyboard,
    get_response_inline_keyboard,
    get_chat_badge,
    safe_reply
)
from agent_runner import AgentRunner

router = Router()

@router.message(F.photo)
async def handle_photo(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    
    # Pick largest photo resolution
    photo = message.photo[-1]
    timestamp = int(time.time())
    filename = f"photo_{timestamp}_{photo.file_unique_id}.jpg"
    file_path = config.UPLOADS_DIR / filename
    
    active_conv = session.get_active_conv()
    initial_title = active_conv.title if active_conv else "Новый диалог"

    status_msg = await safe_reply(
        message,
        f"📥 <i>[Чат: «{html.escape(initial_title)}»] Загружаю и анализирую изображение...</i>"
    )
    
    try:
        # Download from Telegram
        await bot.download(photo, destination=file_path)
        
        caption = message.caption or "Проанализируй это изображение, опиши что на нем и выполни необходимые действия."
        prompt = (
            f"[Пользователь отправил изображение, сохраненное на сервере: {file_path}]\n"
            f"Пожалуйста, изучи этот файл (при необходимости используй инструмент view_file) "
            f"и ответь на запрос пользователя:\n\n{caption}"
        )
        
        async def update_status(text: str):
            try:
                await status_msg.edit_text(f"<i>[Чат: «{html.escape(initial_title)}»]</i>\n{text}", parse_mode="HTML")
            except Exception:
                pass

        runner = AgentRunner(
            session=session,
            prompt=prompt,
            chat_id=message.chat.id,
            on_status=update_status
        )
        session.active_runner = runner
        
        result = await runner.run()
        resp_text = result.get("response", "") or "ℹ️ <i>Агент завершил работу, но не вернул текстового ответа.</i>"
        conv_id = result.get("conversation_id")
        
        session_manager.record_turn(user_id, caption, conv_id)
        
        updated_conv = session.get_active_conv()
        current_title = updated_conv.title if updated_conv else "Диалог"

        html_resp = markdown_to_html(resp_text)
        
        try:
            await status_msg.delete()
        except Exception:
            pass
            
        chunks = split_message(html_resp)
        if chunks:
            badge = get_chat_badge(current_title, session.cwd)
            chunks[0] = badge + chunks[0]

        is_review = (session.mode == "review")
        inline_kb = get_response_inline_keyboard(is_review_mode=is_review)

        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            kb = inline_kb if is_last else None
            await safe_reply(message, chunk, reply_markup=kb)

        # Check for generated / referenced output media files
        media_files = extract_media_files(resp_text)
        for mpath, mtype in media_files:
            if os.path.abspath(mpath) == os.path.abspath(str(file_path)):
                continue
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
        await safe_reply(message, f"❌ <b>Ошибка обработки фото:</b> <code>{html.escape(str(e))}</code>")
    finally:
        session.active_runner = None


@router.message(F.document)
async def handle_document(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    session = session_manager.get_session(user_id)
    doc = message.document
    
    orig_name = doc.file_name or f"doc_{int(time.time())}.dat"
    safe_name = "".join(c for c in orig_name if c.isalnum() or c in "._- ")
    file_path = config.UPLOADS_DIR / safe_name
    
    active_conv = session.get_active_conv()
    initial_title = active_conv.title if active_conv else "Новый диалог"

    status_msg = await safe_reply(
        message,
        f"📥 <i>[Чат: «{html.escape(initial_title)}»] Загружаю документ: {html.escape(safe_name)}...</i>"
    )
    
    try:
        await bot.download(doc, destination=file_path)
        
        caption = message.caption or "Ознакомься с этим файлом и выполни указанные действия."
        prompt = (
            f"[Пользователь загрузил файл на сервер: {file_path} (размер: {doc.file_size or 0} байт)]\n"
            f"Запрос пользователя:\n\n{caption}"
        )
        
        async def update_status(text: str):
            try:
                await status_msg.edit_text(f"<i>[Чат: «{html.escape(initial_title)}»]</i>\n{text}", parse_mode="HTML")
            except Exception:
                pass

        runner = AgentRunner(
            session=session,
            prompt=prompt,
            chat_id=message.chat.id,
            on_status=update_status
        )
        session.active_runner = runner
        
        result = await runner.run()
        resp_text = result.get("response", "") or "ℹ️ <i>Агент завершил работу, но не вернул текстового ответа.</i>"
        conv_id = result.get("conversation_id")
        
        session_manager.record_turn(user_id, caption, conv_id)
        
        updated_conv = session.get_active_conv()
        current_title = updated_conv.title if updated_conv else "Диалог"

        html_resp = markdown_to_html(resp_text)
        
        try:
            await status_msg.delete()
        except Exception:
            pass
            
        chunks = split_message(html_resp)
        if chunks:
            badge = get_chat_badge(current_title, session.cwd)
            chunks[0] = badge + chunks[0]

        is_review = (session.mode == "review")
        inline_kb = get_response_inline_keyboard(is_review_mode=is_review)

        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            kb = inline_kb if is_last else None
            await safe_reply(message, chunk, reply_markup=kb)

        # Check for generated / referenced output media files
        media_files = extract_media_files(resp_text)
        for mpath, mtype in media_files:
            if os.path.abspath(mpath) == os.path.abspath(str(file_path)):
                continue
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
        await safe_reply(message, f"❌ <b>Ошибка обработки файла:</b> <code>{html.escape(str(e))}</code>")
    finally:
        session.active_runner = None
