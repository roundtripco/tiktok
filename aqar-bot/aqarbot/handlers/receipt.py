"""سند القبض: أسئلة قصيرة ثم PDF مرقّم بشعار المكتب."""

from __future__ import annotations

import logging
from datetime import date

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
from ..utils import add_months, format_kwd, month_key, month_label, parse_amount, today_kw
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

KIND, MONTH, PROPERTY, REASON_TEXT, PAYER, AMOUNT, METHOD, NOTES = range(8)

METHODS = {
    "cash": "نقداً",
    "knet": "كي نت",
    "transfer": "تحويل بنكي",
    "cheque": "شيك",
    "link": "رابط دفع",
}

KINDS = {
    "deposit": "عربون",
    "advance": "مقدّم",
    "sale": "بيع",
    "rent": "إيجار",
    "other": "رسوم أخرى ✍️",
}

PROPERTY_PROMPTS = {
    "deposit": "🏠 العربون عن أي عقار؟ (مثال: فيلا الجابرية ق٣)",
    "advance": "🏠 المقدّم عن أي عقار؟ (مثال: عمارة ١٢ - شقة ٥)",
    "sale": "🏠 دفعة البيع عن أي عقار؟ (مثال: أرض صباح الأحمد)",
    "rent": "🏠 العقار أو الوحدة؟ (مثال: عمارة ١٢ - شقة ٥)",
}


def build_reason(kind: str, prop: str | None, month: str | None) -> str:
    if kind == "rent":
        return f"إيجار {prop} لشهر {month}" if prop else f"إيجار شهر {month}"
    if kind == "deposit":
        return f"عربون عن {prop}" if prop else "عربون"
    if kind == "advance":
        return f"مقدّم عن {prop}" if prop else "دفعة مقدّمة"
    return f"دفعة بيع عن {prop}" if prop else "دفعة بيع"


def methods_kb(prefix: str, extra: list | None = None):
    buttons = [InlineKeyboardButton(label, callback_data=f"{prefix}{key}") for key, label in METHODS.items()]
    return grid(buttons, 3, extra)


async def issue_receipt(
    update: Update, context: ContextTypes.DEFAULT_TYPE, office: Office, member: Member, *,
    payer: str, amount_fils: int, reason: str, method: str, notes: str | None = None,
    tenant_id: int | None = None, kind: str = "other",
) -> Receipt | None:
    """يسجّل السند ويرسله PDF. يرجع السند أو None إذا صار خطأ في الملف."""
    receipt = db(context).create_receipt(
        office_id=office.id, payer=payer, amount_fils=amount_fils, reason=reason, method=method,
        notes=notes, created_by=member.user_id, tenant_id=tenant_id, kind=kind,
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
    buttons = [InlineKeyboardButton(label, callback_data=f"rc:kind:{key}") for key, label in KINDS.items()]
    await update.message.reply_text("🧾 سند قبض جديد\n\nنوع الدفعة:", reply_markup=grid(buttons, 2, [CANCEL_BTN]))
    return KIND


async def _clear(update: Update) -> None:
    await update.callback_query.answer()
    await update.callback_query.edit_message_reply_markup(None)


async def _ask_payer(update: Update) -> int:
    await update.effective_message.reply_text("👤 استلمنا من (اسم الدافع):", reply_markup=CANCEL_KB)
    return PAYER


async def _ask_property(update: Update, kind: str) -> int:
    await update.effective_message.reply_text(PROPERTY_PROMPTS[kind], reply_markup=skip_kb("rc:skip"))
    return PROPERTY


async def kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _clear(update)
    key = update.callback_query.data.split(":")[2]
    context.user_data["rc"]["kind"] = key
    if key == "other":
        await update.effective_message.reply_text("✍️ اكتب نوع الرسوم (مثال: رسوم عقد، عمولة، تأمين):", reply_markup=CANCEL_KB)
        return REASON_TEXT
    if key == "rent":
        today = today_kw()
        months = [add_months(today.replace(day=1), delta) for delta in (-1, 0, 1)]
        buttons = [InlineKeyboardButton(month_label(m), callback_data=f"rc:month:{month_key(m)}") for m in months]
        await update.effective_message.reply_text("📅 إيجار أي شهر؟", reply_markup=grid(buttons, 3, [CANCEL_BTN]))
        return MONTH
    return await _ask_property(update, key)


async def month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _clear(update)
    year, mon = map(int, update.callback_query.data.split(":")[2].split("-"))
    context.user_data["rc"]["month"] = month_label(date(year, mon, 1))
    return await _ask_property(update, "rent")


async def prop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data["rc"]
    if update.callback_query:
        await _clear(update)
        value = None
    else:
        value = update.message.text.strip()
        if len(value) > 50:
            await update.message.reply_text("اختصر اسم العقار (أقل من ٥٠ حرف):", reply_markup=skip_kb("rc:skip"))
            return PROPERTY
    data["reason"] = build_reason(data["kind"], value, data.get("month"))
    return await _ask_payer(update)


async def reason_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) > 80:
        await update.message.reply_text("السبب طويل، اختصره لأقل من ٨٠ حرف:")
        return REASON_TEXT
    context.user_data["rc"]["reason"] = text
    return await _ask_payer(update)


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
    await update.message.reply_text("طريقة الدفع:", reply_markup=methods_kb("rc:method:", [CANCEL_BTN]))
    return METHOD


async def method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _clear(update)
    context.user_data["rc"]["method"] = METHODS[update.callback_query.data.split(":")[2]]
    await update.effective_message.reply_text(
        "📝 ملاحظات؟ (مثال: رقم الشيك)", reply_markup=skip_kb("rc:skip")
    )
    return NOTES


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await _clear(update)
        note = None
    else:
        note = update.message.text.strip()[:120]
    data = context.user_data.pop("rc")
    data.pop("month", None)
    result = await get_office_member(update, context)
    if result:
        office, member = result
        await issue_receipt(update, context, office, member, notes=note, **data)
    return ConversationHandler.END


def build_handler() -> ConversationHandler:
    skip = r"^rc:skip$"
    return ConversationHandler(
        entry_points=[CommandHandler("receipt", start), MessageHandler(filters.Text([BTN_RECEIPT]), start)],
        states={
            KIND: [CallbackQueryHandler(kind, pattern=r"^rc:kind:\w+$")],
            MONTH: [CallbackQueryHandler(month, pattern=r"^rc:month:\d{4}-\d{2}$")],
            PROPERTY: [MessageHandler(TEXT_INPUT, prop), CallbackQueryHandler(prop, pattern=skip)],
            REASON_TEXT: [MessageHandler(TEXT_INPUT, reason_text)],
            PAYER: [MessageHandler(TEXT_INPUT, payer)],
            AMOUNT: [MessageHandler(TEXT_INPUT, amount)],
            METHOD: [CallbackQueryHandler(method, pattern=r"^rc:method:\w+$")],
            NOTES: [MessageHandler(TEXT_INPUT, notes), CallbackQueryHandler(notes, pattern=skip)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CommandHandler("cancel", cancel),
            MessageHandler(MENU_FILTER, end_silently),
        ],
        allow_reentry=True,
        name="receipt",
    )
