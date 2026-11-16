"""إعدادات المكتب، الوسطاء، تجديد الاشتراك، وأوامر الإدارة."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from html import escape

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..config import Config
from ..db import Database, Office
from ..documents import COLORS
from ..utils import display_phone, format_date, normalize_phone, today_kw
from .common import (
    BTN_OFFICE,
    CANCEL_KB,
    MAIN_MENU,
    MENU_FILTER,
    TEXT_INPUT,
    cancel,
    config,
    db,
    end_silently,
    get_office_member,
    renew_kb,
    renew_text,
)
from .onboarding import IMAGE_INPUT, color_kb, invite_link, save_image

EDIT_VALUE = 0
LINK_VALUE = 0
LINK_REQUEST_COOLDOWN = 10 * 60  # ثواني
URL_RE = re.compile(r"^https?://\S+$")

EDIT_PROMPTS = {
    "name": "اكتب اسم المكتب الجديد:",
    "phone": "اكتب رقم التواصل الجديد:",
    "logo": "أرسل الشعار الجديد (الأفضل كملف PNG):",
}


def status_line(office) -> str:
    left = office.days_left()
    if left < 0:
        return f"⛔️ منتهي من {format_date(office.paid_until)}"
    return f"✅ فعال لين {format_date(office.paid_until)} (باقي {left} يوم)"


def office_kb(is_owner: bool) -> InlineKeyboardMarkup | None:
    if not is_owner:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ الاسم", callback_data="oe:name"),
         InlineKeyboardButton("📞 الرقم", callback_data="oe:phone")],
        [InlineKeyboardButton("🖼 الشعار", callback_data="oe:logo"),
         InlineKeyboardButton("🎨 اللون", callback_data="oe:color")],
        [InlineKeyboardButton("👥 الوسطاء", callback_data="om:list"),
         InlineKeyboardButton("💳 تجديد الاشتراك", callback_data="os:renew")],
    ])


async def show_office(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = await get_office_member(update, context, need_active=False)
    if not result:
        return
    office, member = result
    members = db(context).list_members(office.id)
    text = (
        f"🏢 <b>{escape(office.name)}</b>\n"
        f"📞 {display_phone(office.phone)}\n"
        f"🎨 اللون: {COLORS.get(office.color, COLORS['navy'])[0]}\n"
        f"👥 عدد الأعضاء: {len(members)}\n"
        f"💳 الاشتراك: {status_line(office)}\n"
        f"🔑 كود المكتب: <code>{office.code}</code>"
    )
    if member.role == "owner":
        text += f"\n\nرابط إضافة وسيط:\n{invite_link(context, office)}"
    await update.effective_message.reply_text(text, reply_markup=office_kb(member.role == "owner"))


async def _owner_office(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = db(context).get_member(update.effective_user.id)
    if member is None or member.role != "owner":
        await update.callback_query.answer("هذا الخيار لصاحب المكتب فقط", show_alert=True)
        return None
    return db(context).get_office(member.office_id)


# ---------- تعديل البيانات ----------

async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _owner_office(update, context):
        return ConversationHandler.END
    field = update.callback_query.data.split(":")[1]
    await update.callback_query.answer()
    context.user_data["edit"] = field
    await update.effective_message.reply_text(EDIT_PROMPTS[field], reply_markup=CANCEL_KB)
    return EDIT_VALUE


async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    field = context.user_data.get("edit")
    member = db(context).get_member(update.effective_user.id)
    message = update.message
    if field == "name" and message.text and 2 <= len(message.text.strip()) <= 40:
        value = message.text.strip()
    elif field == "phone" and message.text and normalize_phone(message.text):
        value = normalize_phone(message.text)
    elif field == "logo" and (value := await save_image(message, context, f"o{member.office_id}")):
        field = "logo_path"
    else:
        await message.reply_text("القيمة غير صحيحة، جرّب مرة ثانية:", reply_markup=CANCEL_KB)
        return EDIT_VALUE
    db(context).update_office(member.office_id, **{field: value})
    context.user_data.clear()
    await message.reply_text("تم التحديث ✅", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def color_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _owner_office(update, context):
        return
    await update.callback_query.answer()
    await update.effective_message.reply_text("اختر اللون:", reply_markup=color_kb("oc:"))


async def color_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    office = await _owner_office(update, context)
    if not office:
        return
    key = update.callback_query.data.split(":")[1]
    db(context).update_office(office.id, color=key)
    await update.callback_query.answer("تم ✅")
    await update.callback_query.edit_message_text(f"تم تغيير اللون إلى {COLORS[key][0]} ✅")


# ---------- الوسطاء ----------

async def members_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    office = await _owner_office(update, context)
    if not office:
        return
    await update.callback_query.answer()
    members = db(context).list_members(office.id)
    agents = [m for m in members if m.role == "agent"]
    lines = [f"👥 أعضاء <b>{escape(office.name)}</b>:"]
    lines += [f"{'👑' if m.role == 'owner' else '👤'} {escape(m.name)}" for m in members]
    lines.append(f"\nلإضافة وسيط أرسل له:\n{invite_link(context, office)}")
    buttons = [[InlineKeyboardButton(f"❌ إزالة {m.name}", callback_data=f"om:rm:{m.user_id}")] for m in agents]
    await update.effective_message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
    )


async def member_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    office = await _owner_office(update, context)
    if not office:
        return
    user_id = int(update.callback_query.data.split(":")[2])
    removed = db(context).remove_member(user_id, office.id)
    await update.callback_query.answer("تمت الإزالة ✅" if removed else "غير موجود")
    await update.callback_query.edit_message_reply_markup(None)


# ---------- الاشتراك ----------

async def renew(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    office = await _owner_office(update, context)
    if not office:
        return
    await update.callback_query.answer()
    await update.effective_message.reply_text(renew_text(context, office), reply_markup=renew_kb(context))


async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    office = await _owner_office(update, context)
    if not office:
        return
    await update.callback_query.answer()
    await update.callback_query.edit_message_reply_markup(None)
    await update.effective_message.reply_text("شكراً 🙏 وصلنا تنبيهك، وبنفعّل الاشتراك بعد التأكد من الدفع.")
    db(context).add_request(office.id, "paid")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"تفعيل {m} شهر", callback_data=f"adm:act:{office.id}:{m}") for m in (1, 3, 12)
    ]])
    for admin_id in config(context).admin_ids:
        await context.bot.send_message(
            admin_id,
            f"💳 مكتب يقول إنه دفع:\n<b>{escape(office.name)}</b>\nالكود: <code>{office.code}</code>\n"
            f"📞 {display_phone(office.phone)}\nالاشتراك الحالي لين: {format_date(office.paid_until)}",
            reply_markup=kb,
        )


async def request_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """صاحب المكتب يطلب رابط دفع، والطلب يوصل للمدير."""
    office = await _owner_office(update, context)
    if not office:
        return
    last = db(context).last_open_request(office.id, "link")
    if last and (datetime.now() - last).total_seconds() < LINK_REQUEST_COOLDOWN:
        await update.callback_query.answer("طلبك وصل، بيوصلك الرابط قريباً 🙏", show_alert=True)
        return
    db(context).add_request(office.id, "link")
    await update.callback_query.answer()
    await update.effective_message.reply_text("وصل طلبك ✅ بيوصلك رابط الدفع هنا في البوت قريباً.")
    cfg = config(context)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📎 أرسل رابط الدفع", callback_data=f"adm:link:{office.id}")]])
    for admin_id in cfg.admin_ids:
        await context.bot.send_message(
            admin_id,
            f"💳 مكتب يطلب رابط دفع ({cfg.price_kwd} د.ك):\n<b>{escape(office.name)}</b>\n"
            f"الكود: <code>{office.code}</code>\n📞 {display_phone(office.phone)}\n"
            f"الاشتراك الحالي لين: {format_date(office.paid_until)}\n\n"
            "سوِّ رابط من UPay واضغط الزر تحت والصقه.",
            reply_markup=kb,
        )


async def send_link_to_office(bot: Bot, cfg: Config, database: Database, office: Office, url: str) -> None:
    await bot.send_message(
        office.owner_id,
        f"💳 رابط دفع اشتراك <b>{escape(office.name)}</b> ({cfg.price_kwd} د.ك):\n{escape(url)}\n\n"
        "⏳ الرابط صالح ٢٤ ساعة.\nبعد الدفع اضغط «✅ دفعت» تحت.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ دفعت", callback_data="os:paid")]]),
    )
    database.resolve_requests(office.id, "link")


async def admin_link_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update, context):
        await update.callback_query.answer()
        return ConversationHandler.END
    office = db(context).get_office(int(update.callback_query.data.split(":")[2]))
    await update.callback_query.answer()
    context.user_data.clear()
    context.user_data["link_office"] = office.id
    await update.effective_message.reply_text(
        f"الصق رابط الدفع لـ <b>{escape(office.name)}</b>:", reply_markup=CANCEL_KB
    )
    return LINK_VALUE


async def admin_link_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    if not URL_RE.match(url):
        await update.message.reply_text("هذا مو رابط. الصق الرابط كامل (يبدأ بـ https://):", reply_markup=CANCEL_KB)
        return LINK_VALUE
    office = db(context).get_office(context.user_data.pop("link_office"))
    await send_link_to_office(context.bot, config(context), db(context), office, url)
    await update.message.reply_text(f"تم إرسال الرابط لـ {escape(office.name)} ✅", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def admin_sendlink_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        return
    if len(context.args) != 2 or not URL_RE.match(context.args[1]):
        await update.message.reply_text("الاستخدام: /sendlink كود_المكتب الرابط")
        return
    office = db(context).get_office_by_code(context.args[0])
    if office is None:
        await update.message.reply_text("ما لقيت مكتب بهذا الكود.")
        return
    await send_link_to_office(context.bot, config(context), db(context), office, context.args[1])
    await update.message.reply_text(f"تم إرسال الرابط لـ {escape(office.name)} ✅")


# ---------- الإدارة ----------

def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return update.effective_user.id in config(context).admin_ids


async def notify_activation(bot: Bot, office: Office) -> None:
    await bot.send_message(
        office.owner_id,
        f"✅ تم تفعيل اشتراك <b>{escape(office.name)}</b> لين {format_date(office.paid_until)}. شكراً لك!",
    )


async def admin_activate_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        await update.callback_query.answer()
        return
    _, _, office_id, months = update.callback_query.data.split(":")
    office = db(context).extend_subscription(
        int(office_id), int(months), update.effective_user.id, int(months) * config(context).price_kwd * 1000
    )
    await update.callback_query.answer("تم التفعيل ✅")
    await update.callback_query.edit_message_text(
        f"✅ تم تفعيل {escape(office.name)} لين {format_date(office.paid_until)}"
    )
    await notify_activation(context.bot, office)


async def admin_activate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        return
    if len(context.args) != 2 or not context.args[1].isdigit():
        await update.message.reply_text("الاستخدام: /activate كود_المكتب عدد_الأشهر")
        return
    office = db(context).get_office_by_code(context.args[0])
    if office is None:
        await update.message.reply_text("ما لقيت مكتب بهذا الكود.")
        return
    months = int(context.args[1])
    office = db(context).extend_subscription(
        office.id, months, update.effective_user.id, months * config(context).price_kwd * 1000
    )
    await update.message.reply_text(f"✅ {escape(office.name)} فعال لين {format_date(office.paid_until)}")
    await notify_activation(context.bot, office)


def admin_report(context: ContextTypes.DEFAULT_TYPE, days: int = 7) -> str:
    offices = db(context).list_offices()
    today = today_kw()
    usage = db(context).usage_summary(today - timedelta(days=days))
    active = [o for o in offices if o.is_active(today)]
    cfg = config(context)
    lines = [
        f"📊 <b>تقرير {cfg.service_name}</b>",
        f"المكاتب: {len(offices)} (فعال: {len(active)})",
        f"الدخل المتوقع شهرياً لو كل الفعالين دفعوا: {len(active) * cfg.price_kwd} د.ك",
        f"\nالاستخدام آخر {days} أيام:",
    ]
    for o in offices:
        u = usage.get(o.id, {})
        lines.append(
            f"• {escape(o.name)} <code>{o.code}</code> — لين {format_date(o.paid_until)}"
            f" | بطاقات {u.get('card', 0)} · سندات {u.get('receipt', 0)}"
        )
    return "\n".join(lines)


async def dashboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        return
    dashboard = context.bot_data.get("dashboard")
    if dashboard is None:
        await update.message.reply_text("لوحة التحكم مو مفعّلة. أضف DASHBOARD_URL في ملف .env وأعد تشغيل البوت.")
        return
    await update.message.reply_text(
        f"🔐 رابط دخول لوحة التحكم (صالح ١٥ دقيقة ولمرة وحدة):\n{dashboard.login_link()}",
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update, context):
        await update.message.reply_text(admin_report(context))


def build_handlers():
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern=r"^oe:(name|phone|logo)$")],
        states={EDIT_VALUE: [MessageHandler(TEXT_INPUT | IMAGE_INPUT, edit_value)]},
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CommandHandler("cancel", cancel),
            MessageHandler(MENU_FILTER, end_silently),
        ],
        allow_reentry=True,
        name="office_edit",
    )
    link_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_link_start, pattern=r"^adm:link:\d+$")],
        states={LINK_VALUE: [MessageHandler(TEXT_INPUT, admin_link_value)]},
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CommandHandler("cancel", cancel),
            MessageHandler(MENU_FILTER, end_silently),
        ],
        allow_reentry=True,
        name="admin_link",
    )
    simple = [
        CommandHandler("office", show_office),
        MessageHandler(filters.Text([BTN_OFFICE]), show_office),
        CallbackQueryHandler(color_menu, pattern=r"^oe:color$"),
        CallbackQueryHandler(color_set, pattern=r"^oc:\w+$"),
        CallbackQueryHandler(members_list, pattern=r"^om:list$"),
        CallbackQueryHandler(member_remove, pattern=r"^om:rm:\d+$"),
        CallbackQueryHandler(renew, pattern=r"^os:renew$"),
        CallbackQueryHandler(paid, pattern=r"^os:paid$"),
        CallbackQueryHandler(request_link, pattern=r"^os:link$"),
        CommandHandler("sendlink", admin_sendlink_cmd),
        CommandHandler("admin", admin_cmd),
        CommandHandler("dashboard", dashboard_cmd),
        CommandHandler("activate", admin_activate_cmd),
        CallbackQueryHandler(admin_activate_cb, pattern=r"^adm:act:\d+:\d+$"),
    ]
    return [edit_conv, link_conv], simple
