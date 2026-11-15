"""تجهيز بطاقة العقار وسند القبض من البيانات."""

from __future__ import annotations

from dataclasses import dataclass, field

from .db import Office, Receipt
from .render import Renderer, data_uri, file_data_uri, render_html
from .utils import amount_in_words, display_phone, format_date, format_kwd

COLORS = {
    "navy": ("كحلي", "#1F3A5F"),
    "green": ("أخضر", "#1E6B52"),
    "maroon": ("عنابي", "#7A1F3D"),
    "gold": ("ذهبي", "#8C6D23"),
    "teal": ("فيروزي", "#0F6E7A"),
    "charcoal": ("رمادي داكن", "#2F3640"),
}

DEALS = {"rent": "للإيجار", "sale": "للبيع"}

PROPERTY_TYPES = {
    "apartment": "شقة",
    "floor": "دور",
    "villa": "فيلا",
    "house": "بيت",
    "chalet": "شاليه",
    "land": "أرض",
    "shop": "محل تجاري",
    "office": "مكتب",
    "building": "عمارة",
}

# أنواع ما يناسبها سؤال الغرف والحمامات
NO_ROOMS = {"land", "shop", "office", "building"}

MAX_PHOTOS = 5
MAX_FEATURES = 6


@dataclass
class PropertyCard:
    deal: str
    ptype: str
    area: str
    price_fils: int | None = None
    price_text: str | None = None
    size_m2: int | None = None
    rooms: int | None = None
    baths: int | None = None
    features: list[str] = field(default_factory=list)


def color_hex(office: Office) -> str:
    return COLORS.get(office.color, COLORS["navy"])[1]


def card_title(card: PropertyCard) -> str:
    return f"{PROPERTY_TYPES[card.ptype]} {DEALS[card.deal]}"


def card_price(card: PropertyCard) -> tuple[str, str | None]:
    if card.price_fils is None:
        return card.price_text or "على السوم", None
    return format_kwd(card.price_fils), ("شهرياً" if card.deal == "rent" else None)


def card_specs(card: PropertyCard) -> list[dict]:
    specs = []
    if card.size_m2:
        specs.append({"icon": "size", "label": f"{card.size_m2:,} م²"})
    if card.rooms:
        specs.append({"icon": "bed", "label": "غرفة واحدة" if card.rooms == 1 else f"{card.rooms} غرف"})
    if card.baths:
        specs.append({"icon": "bath", "label": "حمام واحد" if card.baths == 1 else f"{card.baths} حمامات"})
    return specs


def card_caption(card: PropertyCard, office: Office) -> str:
    """نص جاهز للنسخ مع الصورة في الواتساب أو الانستقرام."""
    price, suffix = card_price(card)
    lines = [f"🏠 {card_title(card)} في {card.area}", f"💰 السعر: {price}{' ' + suffix if suffix else ''}"]
    for spec in card_specs(card):
        lines.append(f"▫️ {spec['label']}")
    for feat in card.features:
        lines.append(f"✅ {feat}")
    lines.append(f"\n📞 للتواصل: {display_phone(office.phone)}\n{office.name}")
    return "\n".join(lines)


async def render_card(
    renderer: Renderer, office: Office, card: PropertyCard, photos: list[bytes], number: int,
) -> tuple[bytes, bytes]:
    price, suffix = card_price(card)
    html = render_html(
        "card.html",
        color=color_hex(office),
        photos=[data_uri(p) for p in photos[:MAX_PHOTOS]],
        deal_label=DEALS[card.deal],
        number=number,
        title=card_title(card),
        location=card.area,
        price_text=price,
        price_suffix=suffix,
        specs=card_specs(card),
        features=card.features[:MAX_FEATURES],
        logo=file_data_uri(office.logo_path),
        office_name=office.name,
        office_phone=display_phone(office.phone),
    )
    image = await renderer.image(html, 1080, 1350)
    pdf = await renderer.pdf(html, "1080px", "1350px")
    return image, pdf


async def render_receipt(
    renderer: Renderer, office: Office, receipt: Receipt, receiver: str, service_name: str,
) -> bytes:
    html = render_html(
        "receipt.html",
        color=color_hex(office),
        logo=file_data_uri(office.logo_path),
        office_name=office.name,
        office_phone=display_phone(office.phone),
        number=receipt.number,
        date=format_date(receipt.created_at.date()),
        amount=format_kwd(receipt.amount_fils),
        amount_words=amount_in_words(receipt.amount_fils),
        payer=receipt.payer,
        reason=receipt.reason,
        method=receipt.method,
        notes=receipt.notes,
        receiver=receiver,
        service_name=service_name,
    )
    return await renderer.pdf(html, "148mm", "210mm", viewport=(560, 794))
