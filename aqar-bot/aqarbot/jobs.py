"""المهام اليومية: تذكير الإيجارات وتنبيهات انتهاء الاشتراك."""

from __future__ import annotations

import logging
from datetime import date
from html import escape

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .config import Config
from .db import Database
from .handlers.tenants import next_unpaid_month, reminder_message
from .utils import due_date_in_month, format_date, format_kwd, month_key, month_label, today_kw, whatsapp_link

log = logging.getLogger(__name__)

LATE_WINDOW_DAYS = 10


def reminder_kind(days_until_due: int) -> str | None:
    if 1 <= days_until_due <= 3:
        return "before"
    if -2 <= days_until_due <= 0:
        return "due"
    if -LATE_WINDOW_DAYS <= days_until_due <= -3:
        return "late"
    return None


async def _send(bot: Bot, chat_id: int, text: str, markup=None) -> bool:
    try:
        await bot.send_message(chat_id, text, reply_markup=markup)
        return True
    except TelegramError as exc:  # المستخدم حظر البوت مثلاً
        log.warning("تعذر الإرسال إلى %s: %s", chat_id, exc)
        return False


async def send_rent_reminders(bot: Bot, database: Database, today: date) -> int:
    sent = 0
    offices = {o.id: o for o in database.list_offices() if o.is_active(today)}
    for tenant in database.all_active_tenants():
        office = offices.get(tenant.office_id)
        if office is None or tenant.paid_for(today):
            continue
        month = next_unpaid_month(tenant, today)
        due = due_date_in_month(month, tenant.due_day)
        kind = reminder_kind((due - today).days)
        if kind is None or database.reminder_sent(tenant.id, month_key(month), kind):
            continue
        heading = {
            "before": f"⏰ إيجار يستحق بعد {(due - today).days} أيام",
            "due": "📅 إيجار مستحق",
            "late": f"🔴 إيجار متأخر {(today - due).days} أيام",
        }[kind]
        text = (
            f"{heading}\n\n"
            f"👤 <b>{escape(tenant.name)}</b> — {escape(tenant.unit)}\n"
            f"💵 {format_kwd(tenant.amount_fils)} عن شهر {month_label(month)}\n"
            f"📅 تاريخ الاستحقاق: {format_date(due)}"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 أرسل تذكير بالواتساب", url=whatsapp_link(
                tenant.phone, reminder_message(tenant, office, today, late=kind == "late")))],
            [InlineKeyboardButton("✅ تم الدفع", callback_data=f"tn:pay:{tenant.id}")],
        ])
        delivered = False
        for member in database.list_members(office.id):
            delivered |= await _send(bot, member.user_id, text, markup)
        if delivered:
            database.log_reminder(tenant.id, month_key(month), kind)
            sent += 1
    return sent


async def send_subscription_notices(bot: Bot, database: Database, cfg: Config, today: date) -> int:
    sent = 0
    for office in database.list_offices():
        left = office.days_left(today)
        if left == 3:
            text = f"⏳ اشتراك <b>{escape(office.name)}</b> ينتهي بعد ٣ أيام ({format_date(office.paid_until)})."
        elif left == 0:
            text = f"⚠️ اشتراك <b>{escape(office.name)}</b> ينتهي اليوم."
        elif left == -1:
            text = f"⛔️ انتهى اشتراك <b>{escape(office.name)}</b> وتوقفت التذكيرات والخدمات."
        else:
            continue
        text += f"\n\nللتجديد ({cfg.price_kwd} د.ك شهرياً) اضغط ⚙️ المكتب ← 💳 تجديد الاشتراك."
        if await _send(bot, office.owner_id, text):
            sent += 1
    return sent


async def daily_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    database: Database = context.bot_data["db"]
    cfg: Config = context.bot_data["config"]
    today = today_kw()
    reminders = await send_rent_reminders(context.bot, database, today)
    notices = await send_subscription_notices(context.bot, database, cfg, today)
    log.info("المهمة اليومية: %s تذكير إيجار، %s تنبيه اشتراك", reminders, notices)
