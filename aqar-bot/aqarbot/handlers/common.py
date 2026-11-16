"""أدوات مشتركة بين الأوامر: الخدمات، القوائم، التحقق من الاشتراك."""

from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ApplicationHandlerStop, ContextTypes, ConversationHandler, filters

from ..config import Config
from ..db import Database, Member, Office
from ..render import Renderer

BTN_CARD = "🏠 بطاقة عقار"
BTN_RECEIPT = "🧾 سند قبض"
BTN_TENANTS = "👥 المستأجرين"
BTN_OFFICE = "⚙️ المكتب"
MENU_BUTTONS = (BTN_CARD, BTN_RECEIPT, BTN_TENANTS, BTN_OFFICE)

MENU_FILTER = filters.Text(MENU_BUTTONS)
TEXT_INPUT = filters.TEXT & ~filters.COMMAND & ~MENU_FILTER

MAIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CARD), KeyboardButton(BTN_RECEIPT)],
     [KeyboardButton(BTN_TENANTS), KeyboardButton(BTN_OFFICE)]],
    resize_keyboard=True,
    is_persistent=True,
)

CANCEL_BTN = InlineKeyboardButton("✖️ إلغاء", callback_data="cancel")
CANCEL_KB = InlineKeyboardMarkup([[CANCEL_BTN]])


def db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data["config"]


def renderer(context: ContextTypes.DEFAULT_TYPE) -> Renderer:
    return context.bot_data["renderer"]


def skip_kb(data: str, label: str = "⏭ تخطي") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data), CANCEL_BTN]])


def grid(buttons: list[InlineKeyboardButton], cols: int, extra: list[InlineKeyboardButton] | None = None):
    rows = [buttons[i:i + cols] for i in range(0, len(buttons), cols)]
    if extra:
        rows.append(extra)
    return InlineKeyboardMarkup(rows)


def renew_text(context: ContextTypes.DEFAULT_TYPE, office: Office) -> str:
    cfg = config(context)
    lines = [f"💳 الاشتراك: {cfg.price_kwd} د.ك شهرياً للمكتب كامل (عدد الوسطاء مفتوح).", ""]
    if cfg.upay_link:
        lines.append(f"١. ادفع من هذا الرابط:\n{cfg.upay_link}")
        lines.append(f"٢. اكتب كود مكتبك في الملاحظات: <code>{office.code}</code>")
        lines.append("٣. اضغط «✅ دفعت» تحت، ونفعّل اشتراكك بأسرع وقت.")
    else:
        lines.append("١. اضغط «💳 اطلب رابط الدفع»، ويوصلك الرابط هنا في البوت.")
        lines.append("٢. ادفع من الرابط (كي نت أو بطاقة).")
        lines.append("٣. اضغط «✅ دفعت»، ونفعّل اشتراكك بأسرع وقت.")
    if cfg.support_contact:
        lines.append(f"\nللاستفسار: {cfg.support_contact}")
    return "\n".join(lines)


def renew_kb(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    paid = InlineKeyboardButton("✅ دفعت", callback_data="os:paid")
    if config(context).upay_link:
        return InlineKeyboardMarkup([[paid]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("💳 اطلب رابط الدفع", callback_data="os:link")], [paid]])


async def get_office_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, need_active: bool = True,
) -> tuple[Office, Member] | None:
    """يتأكد إن المستخدم عضو في مكتب واشتراكه فعال. يرد على المستخدم إذا لا."""
    member = db(context).get_member(update.effective_user.id)
    reply = update.effective_message.reply_text
    if member is None:
        await reply("أهلاً 👋 لازم تسجّل مكتبك أو تنضم لمكتب أول. اضغط /start")
        return None
    office = db(context).get_office(member.office_id)
    if need_active and not office.is_active():
        if member.role == "owner":
            await reply(
                "⛔️ انتهى اشتراك المكتب.\n\n" + renew_text(context, office),
                reply_markup=renew_kb(context),
            )
        else:
            await reply("⛔️ انتهى اشتراك المكتب. تواصل مع صاحب المكتب لتجديده.")
        return None
    return office, member


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_reply_markup(None)
    await update.effective_message.reply_text("تم الإلغاء 👍", reply_markup=MAIN_MENU)
    raise ApplicationHandlerStop(ConversationHandler.END)


async def end_silently(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """المستخدم ضغط زر من القائمة وسط عملية ثانية: ننهي العملية الحالية بهدوء."""
    context.user_data.clear()
    return ConversationHandler.END


async def stale_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer("ما فيه عملية شغالة")
    await update.callback_query.edit_message_reply_markup(None)

