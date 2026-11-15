"""سند القبض: أسئلة قصيرة ثم PDF مرقّم بشعار المكتب."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InputFile, Update
from telegram.constants import ChatAction
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..db import Member, Office, Receipt
from ..documents import render_receipt
from ..utils import format_kwd, month_label, parse_amount, today_kw
from .common import (
    BTN_RECEIPT,
    CANCEL_BTN,
    CANCEL_KB,
    MAIN_MENU,
    MENU_FILTER,
    TEXT_INPUT,
    cancel,
    config,
    db,
    end_silently,
    get_office_member,
    grid,
    renderer,
    skip_kb,
)

log = logging.getLogger(__name__)

PAYER, AMOUNT, REASON, REASON_TEXT, METHOD, NOTES = range(6)

METHODS = {
    "cash": "نقداً",
    "knet": "كي نت",
    "transfer": "تحويل بنكي",
    "cheque": "شيك",
    "link": "رابط دفع",
}


def reasons() -> dict[str, str]:
    return {
        "rent": f"إيجار شهر {month_label(today_kw())}",
        "deposit": "عربون",
        "commission": "عمولة",
        "insurance": "تأمين",
        "other": "سبب آخر ✍️",
    }


def methods_kb(prefix: str, extra: list | None = None):
    buttons = [InlineKeyboardButton(label, callback_data=f"{prefix}{key}") for key, label in METHODS.items()]
    return grid(buttons, 3, extra)


async def issue_receipt(
    update: Update, context: ContextTypes.DEFAULT_TYPE, office: Office, member: Member, *,
    payer: str, amount_fils: int, reason: str, method: str, notes: str | None = None,
    tenant_id: int | None = None,
) -> Receipt | None:
    """يسجّل السند ويرسله PDF. يرجع السند أو None إذا صار خطأ في الملف."""
    receipt = db(context).create_receipt(
        office_id=office.id, payer=payer, amount_fils=amount_fils, reason=reason, method=method,
        notes=notes, created_by=member.user_id, tenant_id=tenant_id,
    )
    chat = update.effective_chat
    await chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    try:
        pdf = await render_receipt(renderer(context), office, receipt, member.name, config(context).service_name)
    except Exception:
        log.exception("فشل تجهيز السند")
        await chat.send_message(f"تم تسجيل السند رقم {receipt.number} لكن صار خطأ في ملف الـ PDF 😓")
        return receipt
    await chat.send_document(
        InputFile(pdf, filename=f"سند-قبض-{receipt.number:04d}.pdf"),
        caption=f"🧾 سند قبض رقم {receipt.number:04d} — {format_kwd(amount_fils)}",
        reply_markup=MAIN_MENU,
    )
    db(context).log_usage(office.id, "receipt")
    return receipt


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await get_office_member(update, context):
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["rc"] = {}
    await update.message.reply_text("🧾 سند قبض جديد\n\nاستلمنا من (اسم الدافع):", reply_markup=CANCEL_KB)
    return PAYER


async def payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not 2 <= len(text) <= 60:
        await update.message.reply_text("اكتب اسم الدافع (أقل من ٦٠ حرف):")
        return PAYER
    context.user_data["rc"]["payer"] = text
    await update.message.reply_text("💵 المبلغ بالدينار؟ (مثال: 350 أو 350.500)", reply_markup=CANCEL_KB)
    return AMOUNT


async def amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    fils = parse_amount(update.message.text)
    if fils is None:
        await update.message.reply_text("المبلغ غير صحيح. اكتب رقم فقط (مثال: 350):")
        return AMOUNT
    context.user_data["rc"]["amount_fils"] = fils
    buttons = [InlineKeyboardButton(label, callback_data=f"rc:reason:{key}") for key, label in reasons().items()]
    await update.message.reply_text("وذلك عن:", reply_markup=grid(buttons, 2, [CANCEL_BTN]))
    return REASON


async def _ask_method(update: Update) -> int:
    await update.effective_message.reply_text("طريقة الدفع:", reply_markup=methods_kb("rc:method:", [CANCEL_BTN]))
    return METHOD


async def reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(None)
    key = query.data.split(":")[2]
    if key == "other":
        await query.message.reply_text("اكتب السبب (مثال: إيجار شقة ٥ عن شهرين):", reply_markup=CANCEL_KB)
        return REASON_TEXT
    context.user_data["rc"]["reason"] = reasons()[key]
    return await _ask_method(update)


async def reason_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) > 80:
        await update.message.reply_text("السبب طويل، اختصره لأقل من ٨٠ حرف:")
        return REASON_TEXT
    context.user_data["rc"]["reason"] = text
    return await _ask_method(update)


async def method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(None)
    context.user_data["rc"]["method"] = METHODS[query.data.split(":")[2]]
    await query.message.reply_text("📝 ملاحظات؟ (مثال: رقم الشيك أو العقار)", reply_markup=skip_kb("rc:skip"))
    return NOTES


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_reply_markup(None)
        note = None
    else:
        note = update.message.text.strip()[:120]
    data = context.user_data.pop("rc")
    result = await get_office_member(update, context)
    if result:
        office, member = result
        await issue_receipt(update, context, office, member, notes=note, **data)
    return ConversationHandler.END


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("receipt", start), MessageHandler(filters.Text([BTN_RECEIPT]), start)],
        states={
            PAYER: [MessageHandler(TEXT_INPUT, payer)],
            AMOUNT: [MessageHandler(TEXT_INPUT, amount)],
            REASON: [CallbackQueryHandler(reason, pattern=r"^rc:reason:\w+$")],
            REASON_TEXT: [MessageHandler(TEXT_INPUT, reason_text)],
            METHOD: [CallbackQueryHandler(method, pattern=r"^rc:method:\w+$")],
            NOTES: [MessageHandler(TEXT_INPUT, notes), CallbackQueryHandler(notes, pattern=r"^rc:skip$")],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CommandHandler("cancel", cancel),
            MessageHandler(MENU_FILTER, end_silently),
        ],
        allow_reentry=True,
        name="receipt",
    )
