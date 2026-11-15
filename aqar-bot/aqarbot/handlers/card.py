"""بطاقة العقار: أسئلة خطوة بخطوة، ثم صورة وPDF بشعار المكتب."""

from __future__ import annotations

import logging
import re
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ChatAction
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..documents import (
    DEALS,
    MAX_FEATURES,
    MAX_PHOTOS,
    NO_ROOMS,
    PROPERTY_TYPES,
    PropertyCard,
    card_caption,
    render_card,
)
from ..utils import parse_amount, parse_int
from .common import (
    BTN_CARD,
    CANCEL_BTN,
    CANCEL_KB,
    MAIN_MENU,
    MENU_FILTER,
    TEXT_INPUT,
    cancel,
    db,
    end_silently,
    get_office_member,
    grid,
    renderer,
    skip_kb,
)

log = logging.getLogger(__name__)

DEAL, PTYPE, AREA, SIZE, ROOMS, BATHS, PRICE, FEATURES, PHOTOS = range(9)


def _card(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data["card"]


async def _clear_buttons(update: Update) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_reply_markup(None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await get_office_member(update, context):
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["card"] = {"features": [], "photos": []}
    buttons = [InlineKeyboardButton(label, callback_data=f"card:deal:{key}") for key, label in DEALS.items()]
    await update.message.reply_text("🏠 بطاقة عقار جديدة\n\nالعقار:", reply_markup=grid(buttons, 2, [CANCEL_BTN]))
    return DEAL


async def deal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _clear_buttons(update)
    _card(context)["deal"] = update.callback_query.data.split(":")[2]
    buttons = [InlineKeyboardButton(label, callback_data=f"card:type:{key}") for key, label in PROPERTY_TYPES.items()]
    await update.effective_message.reply_text("نوع العقار:", reply_markup=grid(buttons, 3, [CANCEL_BTN]))
    return PTYPE


async def ptype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _clear_buttons(update)
    _card(context)["ptype"] = update.callback_query.data.split(":")[2]
    await update.effective_message.reply_text(
        "📍 المنطقة؟ (مثال: السالمية - قطعة ١٢)", reply_markup=CANCEL_KB
    )
    return AREA


async def area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not 2 <= len(text) <= 45:
        await update.message.reply_text("اكتب المنطقة بشكل مختصر (أقل من ٤٥ حرف):")
        return AREA
    _card(context)["area"] = text
    await update.message.reply_text("📐 المساحة بالمتر المربع؟ (رقم فقط، مثال: 120)",
                                    reply_markup=skip_kb("card:skip"))
    return SIZE


async def _ask_rooms_or_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if _card(context)["ptype"] in NO_ROOMS:
        return await _ask_price(update)
    buttons = [InlineKeyboardButton(str(n), callback_data=f"card:rooms:{n}") for n in range(1, 9)]
    await update.effective_message.reply_text(
        "🛏 عدد الغرف:",
        reply_markup=grid(buttons, 4, [InlineKeyboardButton("⏭ تخطي", callback_data="card:skip"), CANCEL_BTN]),
    )
    return ROOMS


async def size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await _clear_buttons(update)
    else:
        value = parse_int(re.sub(r"[^\d٠-٩,]", "", update.message.text))
        if not value or value > 1_000_000:
            await update.message.reply_text("اكتب المساحة كرقم فقط (مثال: 400):", reply_markup=skip_kb("card:skip"))
            return SIZE
        _card(context)["size_m2"] = value
    return await _ask_rooms_or_price(update, context)


async def rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _clear_buttons(update)
    if update.callback_query.data != "card:skip":
        _card(context)["rooms"] = int(update.callback_query.data.split(":")[2])
    buttons = [InlineKeyboardButton(str(n), callback_data=f"card:baths:{n}") for n in range(1, 7)]
    await update.effective_message.reply_text(
        "🛁 عدد الحمامات:",
        reply_markup=grid(buttons, 6, [InlineKeyboardButton("⏭ تخطي", callback_data="card:skip"), CANCEL_BTN]),
    )
    return BATHS


async def _ask_price(update: Update) -> int:
    await update.effective_message.reply_text(
        "💰 السعر بالدينار؟ (مثال: 350)\nأو اكتب نص مثل «على السوم»", reply_markup=CANCEL_KB
    )
    return PRICE


async def baths(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _clear_buttons(update)
    if update.callback_query.data != "card:skip":
        _card(context)["baths"] = int(update.callback_query.data.split(":")[2])
    return await _ask_price(update)


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    fils = parse_amount(text)
    if fils is not None:
        _card(context)["price_fils"] = fils
    elif len(text) <= 20:
        _card(context)["price_text"] = text
    else:
        await update.message.reply_text("اكتب السعر كرقم أو نص قصير (أقل من ٢٠ حرف):")
        return PRICE
    await update.message.reply_text(
        f"✨ المميزات؟ اكتب كل ميزة بسطر (أقصى شي {MAX_FEATURES})\n\n"
        "مثال:\nمدخل خاص\nتكييف مركزي\nقريب من الخدمات",
        reply_markup=skip_kb("card:skip"),
    )
    return FEATURES


async def _ask_photos(update: Update) -> int:
    await update.effective_message.reply_text(
        f"📸 أرسل صور العقار (من ١ إلى {MAX_PHOTOS})\n"
        "أول صورة تكون الصورة الرئيسية في البطاقة.",
        reply_markup=CANCEL_KB,
    )
    return PHOTOS


async def features(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await _clear_buttons(update)
    else:
        raw = update.message.text.replace("،", "\n").replace(",", "\n")
        items = [line.strip(" -•*✅") for line in raw.splitlines()]
        items = [i for i in items if i]
        if any(len(i) > 32 for i in items):
            await update.message.reply_text("كل ميزة لازم تكون قصيرة (أقل من ٣٢ حرف). اكتبها مرة ثانية:",
                                            reply_markup=skip_kb("card:skip"))
            return FEATURES
        _card(context)["features"] = items[:MAX_FEATURES]
    return await _ask_photos(update)


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photos = _card(context)["photos"]
    if len(photos) >= MAX_PHOTOS:
        return PHOTOS
    tg_file = await update.message.photo[-1].get_file()
    photos.append(bytes(await tg_file.download_as_bytearray()))
    if len(photos) >= MAX_PHOTOS:
        return await finish(update, context)
    await update.message.reply_text(
        f"استلمت {len(photos)} من {MAX_PHOTOS} ✅ أرسل باقي الصور أو اضغط «طلّع البطاقة».",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎨 طلّع البطاقة", callback_data="card:done")]]),
    )
    return PHOTOS


async def need_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("أرسل الصور كصور (مو ملفات)، أو اضغط «طلّع البطاقة» إذا خلصت.")
    return PHOTOS


async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await _clear_buttons(update)
    data = context.user_data.pop("card")
    photos = data.pop("photos")
    if not photos:
        context.user_data["card"] = {**data, "photos": photos}
        await update.effective_message.reply_text("لازم صورة وحدة على الأقل 📸")
        return PHOTOS

    member = db(context).get_member(update.effective_user.id)
    office = db(context).get_office(member.office_id)
    card = PropertyCard(**data)
    chat = update.effective_chat
    status = await update.effective_message.reply_text("⏳ جاري تجهيز البطاقة...")
    await chat.send_action(ChatAction.UPLOAD_PHOTO)
    number = db(context).next_card_number(office.id)
    try:
        image, pdf = await render_card(renderer(context), office, card, photos, number)
    except Exception:
        log.exception("فشل تجهيز البطاقة")
        await status.edit_text("صار خطأ في تجهيز البطاقة 😓 جرّب مرة ثانية.")
        return ConversationHandler.END
    await status.delete()
    await chat.send_photo(InputFile(image, filename=f"card-{number:03d}.jpg"))
    await chat.send_document(InputFile(pdf, filename=f"بطاقة-عقار-{number:03d}.pdf"))
    await chat.send_message(
        "📋 نص جاهز للنسخ مع الصورة:\n\n<code>" + escape(card_caption(card, office)) + "</code>",
        reply_markup=MAIN_MENU,
    )
    db(context).log_usage(office.id, "card")
    return ConversationHandler.END


def build_handler() -> ConversationHandler:
    skip = r"^card:skip$"
    return ConversationHandler(
        entry_points=[CommandHandler("card", start), MessageHandler(filters.Text([BTN_CARD]), start)],
        states={
            DEAL: [CallbackQueryHandler(deal, pattern=r"^card:deal:\w+$")],
            PTYPE: [CallbackQueryHandler(ptype, pattern=r"^card:type:\w+$")],
            AREA: [MessageHandler(TEXT_INPUT, area)],
            SIZE: [MessageHandler(TEXT_INPUT, size), CallbackQueryHandler(size, pattern=skip)],
            ROOMS: [CallbackQueryHandler(rooms, pattern=r"^card:(rooms:\d+|skip)$")],
            BATHS: [CallbackQueryHandler(baths, pattern=r"^card:(baths:\d+|skip)$")],
            PRICE: [MessageHandler(TEXT_INPUT, price)],
            FEATURES: [MessageHandler(TEXT_INPUT, features), CallbackQueryHandler(features, pattern=skip)],
            PHOTOS: [
                MessageHandler(filters.PHOTO, photo),
                CallbackQueryHandler(finish, pattern=r"^card:done$"),
                MessageHandler(TEXT_INPUT | filters.Document.ALL, need_photo),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CommandHandler("cancel", cancel),
            MessageHandler(MENU_FILTER, end_silently),
        ],
        allow_reentry=True,
        name="card",
    )
