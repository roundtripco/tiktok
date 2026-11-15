"""أدوات مساعدة: الأرقام، المبالغ بالدينار الكويتي، التواريخ، أرقام الهواتف."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

KUWAIT_TZ = ZoneInfo("Asia/Kuwait")

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

AR_MONTHS = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]


def today_kw() -> date:
    return datetime.now(KUWAIT_TZ).date()


def to_western_digits(text: str) -> str:
    return text.translate(_ARABIC_DIGITS)


def parse_int(text: str) -> int | None:
    cleaned = to_western_digits(text).replace(",", "").replace("٬", "").strip()
    return int(cleaned) if cleaned.isdigit() else None


def parse_amount(text: str) -> int | None:
    """يحوّل نص المبلغ إلى فلوس (١ دينار = ١٠٠٠ فلس). يرجع None إذا غير صالح."""
    cleaned = to_western_digits(text)
    cleaned = cleaned.replace("٫", ".").replace(",", "").replace("٬", "")
    cleaned = re.sub(r"(د\.?\s*ك|دينار|kwd|kd)", "", cleaned, flags=re.IGNORECASE).strip()
    match = re.fullmatch(r"(\d{1,9})(?:\.(\d{1,3}))?", cleaned)
    if not match:
        return None
    dinars = int(match.group(1))
    fils = int((match.group(2) or "0").ljust(3, "0"))
    total = dinars * 1000 + fils
    return total if total > 0 else None


def format_kwd(fils: int) -> str:
    dinars, rem = divmod(fils, 1000)
    text = f"{dinars:,}"
    if rem:
        text += f".{rem:03d}"
    return f"{text} د.ك"


# ---------- المبلغ بالحروف ----------

_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
_TEENS = {
    10: "عشرة", 11: "أحد عشر", 12: "اثنا عشر", 13: "ثلاثة عشر", 14: "أربعة عشر",
    15: "خمسة عشر", 16: "ستة عشر", 17: "سبعة عشر", 18: "ثمانية عشر", 19: "تسعة عشر",
}
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_HUNDREDS = [
    "", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة",
    "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة",
]


def _below_thousand(n: int) -> str:
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(_HUNDREDS[hundreds])
    if rest:
        if rest < 10:
            parts.append(_ONES[rest])
        elif rest < 20:
            parts.append(_TEENS[rest])
        else:
            tens, ones = divmod(rest, 10)
            parts.append(f"{_ONES[ones]} و{_TENS[tens]}" if ones else _TENS[tens])
    return " و".join(parts)


def _scale(count: int, one: str, two: str, plural: str) -> str:
    if count == 1:
        return one
    if count == 2:
        return two
    words = _below_thousand(count)
    return f"{words} {plural if 3 <= count % 100 <= 10 else one}"


def number_to_words(n: int) -> str:
    if n == 0:
        return "صفر"
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    parts = []
    if millions:
        parts.append(_scale(millions, "مليون", "مليونان", "ملايين"))
    if thousands:
        parts.append(_scale(thousands, "ألف", "ألفان", "آلاف"))
    if units:
        parts.append(_below_thousand(units))
    return " و".join(parts)


def amount_in_words(fils: int) -> str:
    dinars, rem = divmod(fils, 1000)
    parts = []
    if dinars:
        parts.append(f"{number_to_words(dinars)} دينار كويتي")
    if rem:
        parts.append(f"{number_to_words(rem)} فلس")
    return "فقط " + " و".join(parts) + " لا غير"


# ---------- التواريخ ----------

def format_date(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label(d: date) -> str:
    return f"{AR_MONTHS[d.month - 1]} {d.year}"


def add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def due_date_in_month(d: date, due_day: int) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, min(due_day, last))


# ---------- الهواتف والواتساب ----------

def normalize_phone(text: str) -> str | None:
    digits = re.sub(r"\D", "", to_western_digits(text))
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 8:
        digits = "965" + digits
    return digits if 10 <= len(digits) <= 15 else None


def display_phone(phone: str) -> str:
    if phone.startswith("965") and len(phone) == 11:
        return f"{phone[3:7]} {phone[7:]}"
    return "+" + phone


def whatsapp_link(phone: str, message: str) -> str:
    return f"https://wa.me/{phone}?text={quote(message)}"
