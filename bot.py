import asyncio
import logging
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher, BaseMiddleware, types
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import config
from handlers import commands_router, callbacks_router, media_router, chat_router
from quota_manager import quota_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.DATA_DIR / "bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("ClaudeBot")


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.TelegramObject, data: dict):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        user_id = user.id

        # If whitelist is completely empty, auto-register the first user as admin!
        if not config.ALLOWED_USERS:
            logger.info(f"First-time setup: authorizing user {user_id} ({user.full_name}) as primary admin.")
            config.add_allowed_user(user_id)
            config.ADMIN_ID = user_id

        if not config.is_user_allowed(user_id):
            logger.warning(f"Unauthorized access attempt from user_id={user_id} username=@{user.username}")
            if isinstance(event, types.Message):
                await event.answer(
                    f"⛔ <b>Доступ ограничен.</b>\n\n"
                    f"Ваш Telegram User ID: <code>{user_id}</code>\n"
                    f"Чтобы получить доступ, добавьте этот ID в параметр <code>ALLOWED_USER_IDS</code> в файле <code>.env</code>.",
                    parse_mode="HTML"
                )
            elif isinstance(event, types.CallbackQuery):
                await event.answer("⛔ Доступ ограничен. Ваш ID не в белом списке.", show_alert=True)
            return

        return await handler(event, data)


async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="chats", description="💬 Список диалогов и переключение"),
        BotCommand(command="tree", description="🌲 Интерактивное древо файлов / CWD"),
        BotCommand(command="new", description="✨ Новый диалог (сбросить контекст)"),
        BotCommand(command="plan", description="📋 Режим планирования задачи"),
        BotCommand(command="btw", description="💬 Задать попутный вопрос"),
        BotCommand(command="status", description="📊 Статус сервера и агента"),
        BotCommand(command="quota", description="⏳ Проверить лимиты использования"),
        BotCommand(command="exec", description="💻 Выполнить bash-команду"),
        BotCommand(command="cd", description="📂 Сменить рабочую папку"),
        BotCommand(command="ls", description="📁 Список файлов в папке"),
        BotCommand(command="pwd", description="📍 Текущая рабочая папка"),
        BotCommand(command="getfile", description="📥 Скачать файл с сервера"),
        BotCommand(command="model", description="🧠 Выбрать модель ИИ"),
        BotCommand(command="effort", description="⚡ Уровень размышлений"),
        BotCommand(command="mode", description="⚙️ Автопилот / Подтверждения"),
        BotCommand(command="stop", description="🛑 Остановить текущую операцию"),
        BotCommand(command="help", description="❓ Справка по всем командам"),
    ]
    try:
        await bot.set_my_commands(commands)
        logger.info("Bot slash commands set successfully in Telegram menu.")
    except Exception as e:
        logger.warning(f"Failed to set bot commands menu: {e}")


async def main():
    if not config.BOT_TOKEN:
        print("\n" + "=" * 60)
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не задан!")
        print("Пожалуйста, создайте бота через @BotFather в Telegram")
        print("и укажите полученный токен в файле:")
        print(f"  {config.ENV_FILE}")
        print("=" * 60 + "\n")
        return

    logger.info("Starting Claude Code Telegram Bot...")
    logger.info(f"Using claude binary: {config.CLAUDE_BIN}")
    logger.info(f"Default model: {config.DEFAULT_MODEL}, effort: {config.DEFAULT_EFFORT}")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Register authorization middleware
    auth_middleware = AuthMiddleware()
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)

    # Register routers
    dp.include_router(commands_router)
    dp.include_router(callbacks_router)
    dp.include_router(media_router)
    dp.include_router(chat_router)

    # Set Telegram slash command menu
    await set_bot_commands(bot)

    # Drop any pending updates from before start
    await bot.delete_webhook(drop_pending_updates=True)

    bot_info = await bot.get_me()
    logger.info(f"Bot connected successfully as @{bot_info.username} (ID: {bot_info.id})")
    print(f"\n🚀 Бот @{bot_info.username} успешно запущен и готов к работе!\n")

    # Start background quota monitor
    quota_task = asyncio.create_task(quota_manager.start_monitor_loop(bot))

    try:
        await dp.start_polling(bot)
    finally:
        quota_task.cancel()
        try:
            await quota_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
