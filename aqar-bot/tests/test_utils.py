from datetime import date

from aqarbot.utils import (
    add_months,
    amount_in_words,
    display_phone,
    due_date_in_month,
    format_kwd,
    normalize_phone,
    number_to_words,
    parse_amount,
)


def test_parse_amount():
    assert parse_amount("350") == 350_000
    assert parse_amount("٣٥٠٫٥٠٠") == 350_500
    assert parse_amount("350.5") == 350_500
    assert parse_amount("1,250 د.ك") == 1_250_000
    assert parse_amount("12 KD") == 12_000
    assert parse_amount("0") is None
    assert parse_amount("abc") is None
    assert parse_amount("1.2345") is None


def test_format_kwd():
    assert format_kwd(350_000) == "350 د.ك"
    assert format_kwd(185_000_000) == "185,000 د.ك"
    assert format_kwd(350_500) == "350.500 د.ك"


def test_number_to_words():
    cases = {
        1: "واحد", 11: "أحد عشر", 21: "واحد وعشرون", 100: "مائة", 200: "مائتان", 350: "ثلاثمائة وخمسون",
        1000: "ألف", 2000: "ألفان", 3000: "ثلاثة آلاف", 11000: "أحد عشر ألف",
        185000: "مائة وخمسة وثمانون ألف", 1_250_000: "مليون ومائتان وخمسون ألف",
        2_500_750: "مليونان وخمسمائة ألف وسبعمائة وخمسون",
    }
    for n, words in cases.items():
        assert number_to_words(n) == words, n


def test_amount_in_words():
    assert amount_in_words(350_500) == "فقط ثلاثمائة وخمسون دينار كويتي وخمسمائة فلس لا غير"
    assert amount_in_words(250) == "فقط مائتان وخمسون فلس لا غير"


def test_phone():
    assert normalize_phone("٩٩٨٨٧٧٦٦") == "96599887766"
    assert normalize_phone("+965 9988 7766") == "96599887766"
    assert normalize_phone("00971501234567") == "971501234567"
    assert normalize_phone("123") is None
    assert display_phone("96599887766") == "9988 7766"


def test_dates():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert due_date_in_month(date(2026, 2, 1), 31) == date(2026, 2, 28)
