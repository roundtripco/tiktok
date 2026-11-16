"""المستأجرين: القائمة، الإضافة، تسجيل الدفع مع سند تلقائي، والتذكير بالواتساب."""

from __future__ import annotations

from datetime import date
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..db import Office, Tenant
from ..utils import (
    add_months,
    display_phone,
    due_date_in_month,
    format_date,
    format_kwd,
    month_key,
    month_label,
    normalize_phone,
    parse_amount,
    parse_int,
    today_kw,
    whatsapp_link,
)
from .common import (
    BTN_TENANTS,
    CANCEL_BTN,
    CANCEL_KB,
    MAIN_MENU,
    MENU_FILTER,
    TEXT_INPUT,
    cancel,
    db,
    end_silently,
    get_office_member,
)
from .receipt import METHODS, issue_receipt, methods_kb

PAGE_SIZE = 8
T_NAME, T_PHONE, T_UNIT, T_AMOUNT, T_DUE, T_PAID = range(6)


# ---------- منطق الحالة ----------

def next_unpaid_month(tenant: Tenant, today: date) -> date:
    if not tenant.last_paid_month:
        return today.replace(day=1)
    year, month = map(int, tenant.last_paid_month.split("-"))
    return add_months(date(year, month, 1), 1)


def status_icon(tenant: Tenant, today: date) -> str:
    if tenant.paid_for(today):
        return "✅"
    if today > due_date_in_month(today, tenant.due_day) or next_unpaid_month(tenant, today) < today.replace(day=1):
        return "🔴"
    return "⏳"


def reminder_message(tenant: Tenant, office: Office, today: date, late: bool = False) -> str:
    month = next_unpaid_month(tenant, today)
    due = due_date_in_month(month, tenant.due_day)
    if late:
        body = (f"نود تذكيركم بأن إيجار {tenant.unit} لشهر {month_label(month)} بمبلغ {format_kwd(tenant.amount_fils)}"
                f" كان مستحقاً بتاريخ {format_date(due)} ولم يتم سداده بعد.")
    else:
        body = (f"نذكّركم بموعد سداد إيجار {tenant.unit} لشهر {month_label(month)}"
                f" بمبلغ {format_kwd(tenant.amount_fils)}، المستحق بتاريخ {format_date(due)}.")
    return f"السلام عليكم {tenant.name}،\n{body}\nشاكرين تعاونكم 🌹\n{office.name}"


def paid_message(tenant: Tenant, office: Office, month: date, receipt_no: int) -> str:
    return (f"السلام عليكم {tenant.name}،\nتم استلام إيجار {tenant.unit} لشهر {month_label(month)}"
            f" بمبلغ {format_kwd(tenant.amount_fils)}، سند قبض رقم {receipt_no:04d}.\nشكراً لكم 🌹\n{office.name}")


def tenant_details(tenant: Tenant, today: date) -> str:
    month = next_unpaid_month(tenant, today)
    paid = "✅ مدفوع" if tenant.paid_for(today) else f"{status_icon(tenant, today)} غير مدفوع"
    return (
        f"👤 <b>{escape(tenant.name)}</b>\n"
        f"🏠 {escape(tenant.unit)}\n"
        f"📞 {display_phone(tenant.phone)}\n"
        f"💵 {format_kwd(tenant.amount_fils)} شهرياً — يستحق يوم {tenant.due_day} من كل شهر\n"
        f"📅 {month_label(today)}: {paid}\n"
        f"⬅️ الشهر المستحق القادم: {month_label(month)}"
    )


def tenant_kb(tenant: Tenant, office: Office, today: date) -> InlineKeyboardMarkup:
    month = next_unpaid_month(tenant, today)
    late = status_icon(tenant, today) == "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ تسجيل دفع {month_label(month)}", callback_data=f"tn:pay:{tenant.id}")],
        [InlineKeyboardButton("📲 أرسل تذكير بالواتساب",
                              url=whatsapp_link(tenant.phone, reminder_message(tenant, office, today, late)))],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"tn:del:{tenant.id}"),
         InlineKeyboardButton("⬅️ القائمة", callback_data="tn:list:0")],
    ])


# ---------- القائمة والتفاصيل ----------

async def _context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await get_office_member(update, context)


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = await _context(update, context)
    if not result:
        return
    office, _ = result
    page = int(update.callback_query.data.split(":")[2]) if update.callback_query else 0
    today = today_kw()
    tenants = db(context).list_tenants(office.id)
    paid = sum(t.paid_for(today) for t in tenants)
    late = sum(status_icon(t, today) == "🔴" for t in tenants)
    total_due = sum(t.amount_fils for t in tenants if not t.paid_for(today))
    text = (
        f"👥 <b>المستأجرين</b> — {month_label(today)}\n\n"
        f"✅ دفعوا: {paid}   ⏳ باقي: {len(tenants) - paid - late}   🔴 متأخرين: {late}\n"
        f"💰 المتبقي للتحصيل: {format_kwd(total_due) if total_due else '0 د.ك'}"
    )
    if not tenants:
        text = "👥 ما فيه مستأجرين مسجلين.\n\nأضف المستأجرين عشان يذكّرك البوت بمواعيد الإيجار تلقائياً."
    chunk = tenants[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [[InlineKeyboardButton(
        f"{status_icon(t, today)} {t.name} — {t.unit} — يوم {t.due_day}", callback_data=f"tn:view:{t.id}"
    )] for t in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("→ السابق", callback_data=f"tn:list:{page - 1}"))
    if (page + 1) * PAGE_SIZE < len(tenants):
        nav.append(InlineKeyboardButton("التالي ←", callback_data=f"tn:list:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("➕ إضافة مستأجر", callback_data="tn:add")])
    markup = InlineKeyboardMarkup(rows)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def _tenant_from_query(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int = 2):
    result = await _context(update, context)
    if not result:
        return None
    office, member = result
    tenant = db(context).get_tenant(int(update.callback_query.data.split(":")[index]), office.id)
    if tenant is None:
        await update.callback_query.edit_message_text("هذا المستأجر محذوف.")
        return None
    return office, member, tenant


async def view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _tenant_from_query(update, context)
    if found:
        office, _, tenant = found
        today = today_kw()
        await update.callback_query.edit_message_text(
            tenant_details(tenant, today), reply_markup=tenant_kb(tenant, office, today)
        )


async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _tenant_from_query(update, context)
    if found:
        _, _, tenant = found
        month = next_unpaid_month(tenant, today_kw())
        await update.effective_message.reply_text(
            f"تسجيل دفع إيجار {escape(tenant.name)} لشهر {month_label(month)} ({format_kwd(tenant.amount_fils)})\n\n"
            "طريقة الدفع:",
            reply_markup=methods_kb(f"tn:pm:{tenant.id}:", [CANCEL_BTN]),
        )


async def pay_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _tenant_from_query(update, context)
    if not found:
        return
    office, member, tenant = found
    await update.callback_query.edit_message_reply_markup(None)
    month = next_unpaid_month(tenant, today_kw())
    receipt = await issue_receipt(
        update, context, office, member,
        payer=tenant.name, amount_fils=tenant.amount_fils,
        reason=f"إيجار {tenant.unit} لشهر {month_label(month)}",
        method=METHODS[update.callback_query.data.split(":")[3]],
        tenant_id=tenant.id, kind="rent",
    )
    db(context).mark_tenant_paid(tenant.id, month_key(month))
    await update.effective_message.reply_text(
        f"✅ تم تسجيل دفع {escape(tenant.name)} لشهر {month_label(month)}.\n"
        "أرسل للمستأجر إشعار الاستلام 👇 (وأرفق ملف السند إذا تبي)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
            "📲 إشعار الاستلام بالواتساب",
            url=whatsapp_link(tenant.phone, paid_message(tenant, office, month, receipt.number)),
        )]]),
    )


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _tenant_from_query(update, context)
    if found:
        _, _, tenant = found
        await update.callback_query.edit_message_text(
            f"متأكد تبي تحذف <b>{escape(tenant.name)}</b> ({escape(tenant.unit)})؟",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 نعم احذف", callback_data=f"tn:delok:{tenant.id}"),
                InlineKeyboardButton("رجوع", callback_data=f"tn:view:{tenant.id}"),
            ]]),
        )


async def delete_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = await _tenant_from_query(update, context)
    if found:
        office, _, tenant = found
        db(context).deactivate_tenant(tenant.id, office.id)
        await update.callback_query.edit_message_text(
            f"تم حذف {escape(tenant.name)} ✅",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ القائمة", callback_data="tn:list:0")]]),
        )


# ---------- إضافة مستأجر ----------

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _context(update, context):
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["tn"] = {}
    await update.effective_message.reply_text("➕ مستأجر جديد\n\nاسم المستأجر:", reply_markup=CANCEL_KB)
    return T_NAME


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not 2 <= len(text) <= 40:
        await update.message.reply_text("اكتب الاسم (أقل من ٤٠ حرف):")
        return T_NAME
    context.user_data["tn"]["name"] = text
    await update.message.reply_text("📞 رقم المستأجر (للتذكير بالواتساب):", reply_markup=CANCEL_KB)
    return T_PHONE


async def add_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = normalize_phone(update.message.text)
    if phone is None:
        await update.message.reply_text("الرقم غير صحيح. اكتب رقم من ٨ أرقام:")
        return T_PHONE
    context.user_data["tn"]["phone"] = phone
    await update.message.reply_text("🏠 العقار أو الوحدة؟ (مثال: عمارة ١٢ - شقة ٥)", reply_markup=CANCEL_KB)
    return T_UNIT


async def add_unit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not 1 <= len(text) <= 40:
        await update.message.reply_text("اكتب الوحدة باختصار (أقل من ٤٠ حرف):")
        return T_UNIT
    context.user_data["tn"]["unit"] = text
    await update.message.reply_text("💵 الإيجار الشهري بالدينار؟ (مثال: 350)", reply_markup=CANCEL_KB)
    return T_AMOUNT


async def add_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    fils = parse_amount(update.message.text)
    if fils is None:
        await update.message.reply_text("اكتب المبلغ كرقم (مثال: 350):")
        return T_AMOUNT
    context.user_data["tn"]["amount_fils"] = fils
    await update.message.reply_text("📅 يوم استحقاق الإيجار من كل شهر؟ (رقم من 1 إلى 31)", reply_markup=CANCEL_KB)
    return T_DUE


async def add_due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    day = parse_int(update.message.text)
    if day is None or not 1 <= day <= 31:
        await update.message.reply_text("اكتب رقم من 1 إلى 31:")
        return T_DUE
    context.user_data["tn"]["due_day"] = day
    month = month_label(today_kw())
    await update.message.reply_text(
        f"هل دفع إيجار شهر {month}؟",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ نعم دفع", callback_data="tn:paid:yes"),
            InlineKeyboardButton("⏳ لا، باقي", callback_data="tn:paid:no"),
        ]]),
    )
    return T_PAID


async def add_paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(None)
    result = await get_office_member(update, context)
    if not result:
        return ConversationHandler.END
    office, _ = result
    today = today_kw()
    paid_month = today if query.data.endswith("yes") else add_months(today.replace(day=1), -1)
    data = context.user_data.pop("tn")
    tenant = db(context).add_tenant(office_id=office.id, last_paid_month=month_key(paid_month), **data)
    await query.message.reply_text(
        f"تمت إضافة <b>{escape(tenant.name)}</b> ✅\n"
        f"بذكّرك قبل موعد الإيجار بـ ٣ أيام، ويوم الاستحقاق، وإذا تأخر.",
        reply_markup=MAIN_MENU,
    )
    return ConversationHandler.END


def build_handlers():
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_start, pattern=r"^tn:add$")],
        states={
            T_NAME: [MessageHandler(TEXT_INPUT, add_name)],
            T_PHONE: [MessageHandler(TEXT_INPUT, add_phone)],
            T_UNIT: [MessageHandler(TEXT_INPUT, add_unit)],
            T_AMOUNT: [MessageHandler(TEXT_INPUT, add_amount)],
            T_DUE: [MessageHandler(TEXT_INPUT, add_due)],
            T_PAID: [CallbackQueryHandler(add_paid, pattern=r"^tn:paid:(yes|no)$")],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CommandHandler("cancel", cancel),
            MessageHandler(MENU_FILTER, end_silently),
        ],
        allow_reentry=True,
        name="tenant_add",
    )
    simple = [
        CommandHandler("tenants", show_list),
        MessageHandler(filters.Text([BTN_TENANTS]), show_list),
        CallbackQueryHandler(show_list, pattern=r"^tn:list:\d+$"),
        CallbackQueryHandler(view, pattern=r"^tn:view:\d+$"),
        CallbackQueryHandler(pay, pattern=r"^tn:pay:\d+$"),
        CallbackQueryHandler(pay_method, pattern=r"^tn:pm:\d+:\w+$"),
        CallbackQueryHandler(delete, pattern=r"^tn:del:\d+$"),
        CallbackQueryHandler(delete_ok, pattern=r"^tn:delok:\d+$"),
    ]
    return add_conv, simple
