"""تجميع البوت: الأوامر، المهام اليومية، ومعالجة الأخطاء."""

from __future__ import annotations

import logging
import warnings
from datetime import time

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, Defaults
from telegram.request import BaseRequest

from .config import Config
from .db import Database
from .handlers import card, office, onboarding, receipt, tenants
from .handlers.common import stale_cancel
from .jobs import daily_job
from .render import Renderer
from .utils import KUWAIT_TZ

log = logging.getLogger(__name__)

# أزرار المحادثات مربوطة بالمستخدم مو بالرسالة، وهذا مقصود
warnings.filterwarnings("ignore", message=r".*per_message=False.*")

COMMANDS = [
    BotCommand("start", "البداية"),
    BotCommand("card", "بطاقة عقار جديدة"),
    BotCommand("receipt", "سند قبض جديد"),
    BotCommand("tenants", "المستأجرين والإيجارات"),
    BotCommand("office", "إعدادات المكتب والاشتراك"),
    BotCommand("cancel", "إلغاء العملية الحالية"),
]


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("خطأ أثناء معالجة التحديث", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await update.effective_chat.send_message("صار خطأ غير متوقع 😓 جرّب مرة ثانية أو اضغط /start")
        except Exception:  # noqa: BLE001
            pass


def build_application(
    cfg: Config, database: Database, renderer: Renderer, request: BaseRequest | None = None,
) -> Application:
    builder = (
        Application.builder()
        .token(cfg.token)
        .defaults(Defaults(parse_mode=ParseMode.HTML, tzinfo=KUWAIT_TZ, link_preview_options=None))
    )
    if request is not None:
        builder = builder.request(request).get_updates_request(request)

    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands(COMMANDS)

    async def post_shutdown(app: Application) -> None:
        await renderer.stop()
        database.close()

    app = builder.post_init(post_init).post_shutdown(post_shutdown).build()
    app.bot_data.update(db=database, config=cfg, renderer=renderer)

    # كل محادثة في مجموعة مستقلة: لو المستخدم ضغط زر من القائمة وسط محادثة،
    # المحادثة الحالية تنتهي بهدوء والمحادثة الجديدة تبدأ.
    app.add_handler(onboarding.build_handler(), group=0)
    app.add_handler(card.build_handler(), group=1)
    app.add_handler(receipt.build_handler(), group=2)
    tenant_conv, tenant_simple = tenants.build_handlers()
    app.add_handler(tenant_conv, group=3)
    office_conv, office_simple = office.build_handlers()
    app.add_handler(office_conv, group=4)
    for handler in tenant_simple + office_simple:
        app.add_handler(handler, group=5)
    app.add_handler(CallbackQueryHandler(stale_cancel, pattern=r"^cancel$"), group=6)
    app.add_error_handler(on_error)

    if app.job_queue is not None:
        app.job_queue.run_daily(daily_job, time=time(cfg.reminder_hour, 0, tzinfo=KUWAIT_TZ), name="daily")
    return app
