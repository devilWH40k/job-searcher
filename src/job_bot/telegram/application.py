"""Build the Telegram application and run its polling lifecycle."""

import asyncio
import logging

import httpx
from telegram import BotCommand, MenuButtonCommands, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from job_bot.config import Config
from job_bot.services.job_search import JobSearchService
from job_bot.sources.djinni import USER_AGENT, DjinniClient
from job_bot.storage import SavedSearchStorage, VacancyStorage
from job_bot.telegram.handlers import (
    CREATE_BUTTON,
    FIND_BUTTON,
    FINISH_BUTTON,
    HELP_BUTTON,
    LIST_BUTTON,
    choose_categories,
    create_search,
    delete_saved_search,
    finish,
    help_command,
    list_searches,
    load_more,
    on_error,
    retry_save,
    run_saved_search,
    search_keyword,
    select_categories,
    select_source,
    skip_keyword,
    start,
    unknown_command,
)

logger = logging.getLogger(__name__)


def create_application(config: Config) -> Application:
    """Build sequential command handling with explicit HTTP timeouts."""

    async def initialize_search(application: Application) -> None:
        try:
            await application.bot.set_my_commands(
                [
                    BotCommand("start", "🔍 Find a job"),
                    BotCommand("createsearch", "💾 Save search filters"),
                    BotCommand("list", "📋 Your saved searches"),
                    BotCommand("help", "💡 Help & commands"),
                    BotCommand("finish", "✅ Finish search"),
                ]
            )
            await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        except TelegramError:
            logger.warning(
                "Could not configure the Telegram command menu; "
                "commands remain available."
            )
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=10),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
                "Accept-Language": "uk",
            },
            follow_redirects=False,
        )
        application.bot_data["job_search"] = JobSearchService(
            DjinniClient(client), VacancyStorage(config.database_path)
        )
        application.bot_data["saved_searches"] = SavedSearchStorage(
            config.database_path
        )

    async def shutdown_search(application: Application) -> None:
        service = application.bot_data.pop("job_search", None)
        if service is not None:
            await service.aclose()

    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .concurrent_updates(False)
        .connect_timeout(10)
        .read_timeout(10)
        .write_timeout(10)
        .pool_timeout(10)
        .get_updates_connect_timeout(10)
        .get_updates_read_timeout(10)
        .get_updates_write_timeout(10)
        .get_updates_pool_timeout(10)
        .post_init(initialize_search)
        .post_shutdown(shutdown_search)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("createsearch", create_search))
    application.add_handler(CommandHandler("list", list_searches))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("finish", finish))
    application.add_handler(
        CallbackQueryHandler(
            select_source, pattern=r"^source:djinni(?::[0-9a-f]{12})?$"
        )
    )
    application.add_handler(CallbackQueryHandler(select_categories, pattern=r"^cat:"))
    application.add_handler(CallbackQueryHandler(skip_keyword, pattern=r"^skip:"))
    application.add_handler(
        CallbackQueryHandler(choose_categories, pattern=r"^categories:")
    )
    application.add_handler(CallbackQueryHandler(finish, pattern=r"^finish:"))
    application.add_handler(CallbackQueryHandler(retry_save, pattern=r"^savesearch:"))
    application.add_handler(CallbackQueryHandler(list_searches, pattern=r"^savedlist:"))
    application.add_handler(
        CallbackQueryHandler(run_saved_search, pattern=r"^savedrun:")
    )
    application.add_handler(
        CallbackQueryHandler(delete_saved_search, pattern=r"^saveddelete:")
    )
    application.add_handler(
        CallbackQueryHandler(load_more, pattern=r"^more:[0-9a-f]{12}:[0-9]+$")
    )
    application.add_handler(MessageHandler(filters.Text([FIND_BUTTON]), start))
    application.add_handler(
        MessageHandler(filters.Text([CREATE_BUTTON]), create_search)
    )
    application.add_handler(MessageHandler(filters.Text([LIST_BUTTON]), list_searches))
    application.add_handler(MessageHandler(filters.Text([HELP_BUTTON]), help_command))
    application.add_handler(MessageHandler(filters.Text([FINISH_BUTTON]), finish))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, search_keyword)
    )
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    application.add_error_handler(on_error)
    return application


def run_bot(config: Config) -> None:
    """Poll until interrupted, closing HTTP clients and the event loop on exit."""
    # Python 3.14 no longer implicitly creates an event loop for run_polling.
    # Runner owns the loop while python-telegram-bot owns application shutdown.
    with asyncio.Runner() as runner:
        asyncio.set_event_loop(runner.get_loop())
        application = create_application(config)
        logger.info("Starting Telegram long polling. Press Ctrl+C to stop.")
        application.run_polling(
            timeout=30,
            bootstrap_retries=3,
            allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
            drop_pending_updates=False,
            close_loop=False,
        )
    logger.info("Telegram bot stopped.")
