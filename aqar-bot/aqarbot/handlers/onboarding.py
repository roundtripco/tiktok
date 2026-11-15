"""التسجيل: مكتب جديد أو انضمام وسيط لمكتب موجود."""

from __future__ import annotations

import time
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..db import Office
from ..documents import COLORS
from ..utils import display_phone, format_date, normalize_phone
from .common import (
    CANCEL_KB,
    MAIN_MENU,
    MENU_FILTER,
    TEXT_INPUT,
    cancel,
    config,
    db,
    end_silently,
    grid,
    skip_kb,
)

CHOOSE, NAME, PHONE, LOGO, COLOR, JOIN_CODE = range(6)

IMAGE_INPUT = filters.PHOTO | filters.Document.IMAGE


def invite_link(context: ContextTypes.DEFAULT_TYPE, office: Office) -> str:
    return f"https://t.me/{context.bot.username}?start=join_{office.code}"


def color_kb(prefix: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(label, callback_data=f"{prefix}{key}") for key, (label, _) in COLORS.items()]
    return grid(buttons, 3)


async def save_image(message: Message, context: ContextTypes.DEFAULT_TYPE, prefix: str) -> str | None:
    """يحفظ صورة (شعار) أرسلها المستخدم كصورة أو كملف، ويرجع مسارها."""
    if message.photo:
        tg_file, ext = await message.photo[-1].get_file(), "jpg"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        tg_file = await message.document.get_file()
        ext = message.document.mime_type.split("/")[-1].replace("jpeg", "jpg").replace("svg+xml", "svg")
    else:
        return None
    logos = config(context).data_dir / "logos"
    logos.mkdir(parents=True, exist_ok=True)
    path = logos / f"{prefix}_{int(time.time())}.{ext}"
    path.write_bytes(bytes(await tg_file.download_as_bytearray()))
    return str(path)


async def join_office(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> bool:
    office = db(context).get_office_by_code(code)
    if office is None:
        return False
    user = update.effective_user
    db(context).add_agent(user.id, office.id, user.full_name)
    await update.effective_message.reply_text(
        f"تم انضمامك لمكتب <b>{escape(office.name)}</b> ✅\n\nاستخدم الأزرار تحت عشان تبدأ.",
        reply_markup=MAIN_MENU,
    )
    try:
        await context.bot.send_message(office.owner_id, f"👤 انضم {escape(user.full_name)} لمكتبك كوسيط.")
    except Exception:  # noqa: BLE001 - التنبيه اختياري
        pass
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    user = update.effective_user
    member = db(context).get_member(user.id)

    if context.args and context.args[0].startswith("join_"):
        if member and member.role == "owner":
            await update.message.reply_text("أنت صاحب مكتب مسجّل، ما تقدر تنضم لمكتب ثاني بنفس الحساب.")
            return ConversationHandler.END
        if not await join_office(update, context, context.args[0][5:]):
            await update.message.reply_text("رابط الانضمام غير صحيح أو منتهي. اطلب رابط جديد من صاحب المكتب.")
        return ConversationHandler.END

    if member:
        office = db(context).get_office(member.office_id)
        await update.message.reply_text(
            f"هلا {escape(user.first_name)} 👋\nمكتب: <b>{escape(office.name)}</b>\n\nاختر من القائمة تحت.",
            reply_markup=MAIN_MENU,
        )
        return ConversationHandler.END

    cfg = config(context)
    await update.message.reply_text(
        f"هلا وغلا في <b>{cfg.service_name}</b> 🏢\n\n"
        "مساعدك اليومي في المكتب العقاري:\n"
        "🏠 بطاقة عقار بشعار مكتبك جاهزة للواتساب والانستقرام\n"
        "🧾 سندات قبض مرقّمة PDF خلال ثواني\n"
        "⏰ تذكير تلقائي بمواعيد الإيجارات\n\n"
        f"🎁 أول {cfg.trial_days} يوم مجاناً.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏢 تسجيل مكتب جديد", callback_data="reg:new")],
            [InlineKeyboardButton("🔑 عندي كود انضمام لمكتب", callback_data="reg:join")],
        ]),
    )
    return CHOOSE


async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(None)
    if query.data == "reg:join":
        await query.message.reply_text("اكتب كود المكتب (٦ حروف وأرقام) اللي عطاك إياه صاحب المكتب:",
                                       reply_markup=CANCEL_KB)
        return JOIN_CODE
    await query.message.reply_text("ممتاز 👌\n\nوش اسم المكتب؟ (مثال: مكتب الديرة العقاري)", reply_markup=CANCEL_KB)
    return NAME


async def join_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await join_office(update, context, update.message.text):
        return ConversationHandler.END
    await update.message.reply_text("الكود غير صحيح ❌ تأكد منه واكتبه مرة ثانية:", reply_markup=CANCEL_KB)
    return JOIN_CODE


async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not 2 <= len(text) <= 40:
        await update.message.reply_text("الاسم لازم يكون بين ٢ و٤٠ حرف. اكتبه مرة ثانية:")
        return NAME
    context.user_data["reg"] = {"name": text}
    await update.message.reply_text(
        "رقم التواصل اللي يطلع على البطاقات والسندات؟ (مثال: 99887766)", reply_markup=CANCEL_KB
    )
    return PHONE


async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    number = normalize_phone(update.message.text)
    if number is None:
        await update.message.reply_text("الرقم غير صحيح. اكتب رقم كويتي من ٨ أرقام أو رقم دولي كامل:")
        return PHONE
    context.user_data["reg"]["phone"] = number
    await update.message.reply_text(
        "أرسل شعار المكتب 🖼\n(الأفضل ترسله كملف PNG عشان يطلع بجودة عالية)",
        reply_markup=skip_kb("reg:nologo", "⏭ بدون شعار"),
    )
    return LOGO


async def logo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_reply_markup(None)
        context.user_data["reg"]["logo"] = None
    else:
        context.user_data["reg"]["logo"] = await save_image(
            update.message, context, f"u{update.effective_user.id}"
        )
    await update.effective_message.reply_text("آخر خطوة 🎨 اختر لون المكتب:", reply_markup=color_kb("reg:color:"))
    return COLOR


async def color(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(None)
    reg = context.user_data.pop("reg")
    user = update.effective_user
    cfg = config(context)
    office = db(context).create_office(
        name=reg["name"], phone=reg["phone"], color=query.data.rsplit(":", 1)[1],
        logo_path=reg["logo"], owner_id=user.id, owner_name=user.full_name, trial_days=cfg.trial_days,
    )
    await query.message.reply_text(
        f"🎉 تم تسجيل <b>{escape(office.name)}</b>\n\n"
        f"📞 {display_phone(office.phone)}\n"
        f"🎁 التجربة المجانية لين: <b>{format_date(office.paid_until)}</b>\n\n"
        "👥 عشان تضيف الوسطاء، أرسل لهم هذا الرابط:\n"
        f"{invite_link(context, office)}\n\n"
        "ابدأ الحين واضغط «🏠 بطاقة عقار» 👇",
        reply_markup=MAIN_MENU,
    )
    for admin_id in cfg.admin_ids:
        try:
            await context.bot.send_message(
                admin_id, f"🆕 مكتب جديد: {escape(office.name)}\n📞 {display_phone(office.phone)}\nالكود: {office.code}"
            )
        except Exception:  # noqa: BLE001
            pass
    return ConversationHandler.END


async def not_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("أرسل الشعار كصورة أو ملف صورة، أو اضغط «بدون شعار».",
                                    reply_markup=skip_kb("reg:nologo", "⏭ بدون شعار"))
    return LOGO


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE: [CallbackQueryHandler(choose, pattern=r"^reg:(new|join)$")],
            JOIN_CODE: [MessageHandler(TEXT_INPUT, join_code)],
            NAME: [MessageHandler(TEXT_INPUT, name)],
            PHONE: [MessageHandler(TEXT_INPUT, phone)],
            LOGO: [
                MessageHandler(IMAGE_INPUT, logo),
                CallbackQueryHandler(logo, pattern=r"^reg:nologo$"),
                MessageHandler(TEXT_INPUT, not_image),
            ],
            COLOR: [CallbackQueryHandler(color, pattern=r"^reg:color:\w+$")],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CommandHandler("cancel", cancel),
            MessageHandler(MENU_FILTER, end_silently),
        ],
        allow_reentry=True,
        name="onboarding",
    )

