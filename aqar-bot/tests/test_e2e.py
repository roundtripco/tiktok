"""تجربة كاملة للبوت كأنه مكتب حقيقي: تسجيل، وسيط، بطاقة، سند، مستأجرين، تذكير، اشتراك.

تشغيل:  python -m pytest tests
حفظ عينات المخرجات:  AQAR_SAMPLES_DIR=samples python -m pytest tests
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote

from aqarbot.app import build_application
from aqarbot.config import Config
from aqarbot.db import Database
from aqarbot.handlers.common import BTN_CARD, BTN_OFFICE, BTN_RECEIPT, BTN_TENANTS
from aqarbot.jobs import send_rent_reminders, send_subscription_notices
from aqarbot.render import Renderer
from aqarbot.utils import add_months, due_date_in_month, month_key, month_label, today_kw

from .fake_telegram import Client, FakeTelegram, texts
from .scenes import make_images

OWNER, AGENT, ADMIN, STRANGER = 1001, 1002, 9999, 5555


def _files(calls, method):
    return [c for c in calls if c.method == method and c.files]


def _save(name: str, content: bytes) -> None:
    out = os.environ.get("AQAR_SAMPLES_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        Path(out, name).write_bytes(content)


async def scenario(data_dir: Path) -> None:
    cfg = Config(
        token="123:TEST", admin_ids=frozenset({ADMIN}), data_dir=data_dir, service_name="مساعد المكتب العقاري",
        upay_link="", price_kwd=12, trial_days=14, reminder_hour=9,
        support_contact="",
    )
    database = Database(data_dir / "test.db")
    renderer = Renderer()
    tg = FakeTelegram()
    app = build_application(cfg, database, renderer, request=tg)
    scenes, logo = await make_images(renderer)

    async with app:
        owner = Client(app, tg, OWNER, "عبدالله", "الديرة")
        agent = Client(app, tg, AGENT, "فهد", "العتيبي")
        admin = Client(app, tg, ADMIN, "المدير")
        stranger = Client(app, tg, STRANGER, "غريب")

        # ---------- غير مسجل ----------
        out = await stranger.send(BTN_CARD)
        assert "لازم تسجّل" in texts(out)

        # ---------- تسجيل مكتب ----------
        out = await owner.send("/start")
        assert "reg:new" in out[-1].callback_data()
        await owner.press("reg:new")
        out = await owner.send("ا")  # اسم قصير مرفوض
        assert "بين ٢ و٤٠" in texts(out)
        await owner.send("مكتب الديرة العقاري")
        out = await owner.send("123")  # رقم غلط
        assert "غير صحيح" in texts(out)
        await owner.send("٩٩٨٨٧٧٦٦")
        await owner.document(logo, "image/jpeg", "logo.jpg")
        out = await owner.press("reg:color:green")
        welcome = texts(out)
        assert "تم تسجيل" in welcome and "التجربة المجانية" in welcome
        office = database.get_office(database.get_member(OWNER).office_id)
        assert office.phone == "96599887766" and office.logo_path and office.color == "green"
        assert office.days_left() == 14
        link = re.search(r"https://t\.me/AqarTestBot\?start=join_(\w+)", welcome)
        assert link and link.group(1) == office.code
        assert any(str(c.params.get("chat_id")) == str(ADMIN) and "مكتب جديد" in c.text for c in out)

        # ---------- انضمام وسيط ----------
        out = await agent.send(f"/start join_{office.code}")
        assert "تم انضمامك" in texts(out)
        assert database.get_member(AGENT).role == "agent"
        out = await stranger.send("/start join_WRONG1")
        assert "غير صحيح" in texts(out)

        # ---------- بطاقة عقار: شقة للإيجار بأربع صور ----------
        await owner.send(BTN_CARD)
        await owner.press("card:deal:rent")
        await owner.press("card:type:apartment")
        await owner.send("السالمية - قطعة ١٢")
        await owner.send("١٢٠ م")
        await owner.press("card:rooms:3")
        await owner.press("card:baths:2")
        await owner.send("350")
        await owner.send("مدخل خاص\nتكييف مركزي\nموقف سيارة\nقريب من الخدمات")
        for key in ("living", "kitchen", "bedroom"):
            await owner.photo(scenes[key])
        await owner.photo(scenes["building"])
        out = await owner.press("card:done")
        photos, docs = _files(out, "sendPhoto"), _files(out, "sendDocument")
        assert len(photos) == 1 and len(docs) == 1
        image = photos[0].files["photo"][1]
        pdf = docs[0].files["document"][1]
        assert image[:2] == b"\xff\xd8" and pdf[:4] == b"%PDF"
        _save("card-rent.jpg", image)
        _save("card-rent.pdf", pdf)
        caption = texts(out)
        assert "شقة للإيجار في السالمية" in caption and "350 د.ك شهرياً" in caption and "3 غرف" in caption

        # ---------- بطاقة: أرض للبيع، الوسيط، صورة وحدة، تخطي المساحة ----------
        await agent.send("/card")
        await agent.press("card:deal:sale")
        await agent.press("card:type:land")
        await agent.send("صباح الأحمد البحرية")
        out = await agent.press("card:skip")
        assert "السعر" in texts(out)  # الأرض ما تسأل عن الغرف
        await agent.send("على السوم")
        await agent.press("card:skip")
        out = await agent.send("نص بدل صورة")
        assert "أرسل الصور" in texts(out)
        await agent.photo(scenes["building"])
        out = await agent.press("card:done")
        _save("card-land.jpg", _files(out, "sendPhoto")[0].files["photo"][1])
        assert "على السوم" in texts(out)

        # ---------- سند قبض: عربون، النوع أول سؤال ----------
        out = await agent.send(BTN_RECEIPT)
        assert {"rc:kind:rent", "rc:kind:deposit", "rc:kind:sale", "rc:kind:commission"} <= set(out[-1].callback_data())
        await agent.press("rc:kind:deposit")
        await agent.send("شقة ٥ - عمارة ١٢ السالمية")
        await agent.send("محمد عبدالله الكندري")
        out = await agent.send("abc")
        assert "غير صحيح" in texts(out)
        await agent.send("٣٥٠٫٥٠٠")
        await agent.press("rc:method:knet")
        out = await agent.press("rc:skip")
        docs = _files(out, "sendDocument")
        assert len(docs) == 1 and "سند قبض رقم 0001" in docs[0].text and "350.500 د.ك" in docs[0].text
        _save("receipt.pdf", docs[0].files["document"][1])

        # سند إيجار لشهر محدد، ودفعة بيع بدون عقار، وسبب مكتوب
        await owner.send(BTN_RECEIPT)
        out = await owner.press("rc:kind:rent")
        month_buttons = [d for d in out[-1].callback_data() if d.startswith("rc:month:")]
        assert len(month_buttons) == 3
        await owner.press(month_buttons[2])  # الشهر الجاي (دفع مقدّم)
        await owner.send("عمارة ١٢ - شقة ٨")
        await owner.send("سارة الفهد")
        await owner.send("420")
        await owner.press("rc:method:transfer")
        await owner.send("تحويل بنك بوبيان")
        await owner.send(BTN_RECEIPT)
        await owner.press("rc:kind:sale")
        await owner.press("rc:skip")
        await owner.send("خالد")
        await owner.send("5000")
        await owner.press("rc:method:cheque")
        await owner.press("rc:skip")
        await owner.send(BTN_RECEIPT)
        await owner.press("rc:kind:other")
        await owner.send("رسوم عقد")
        await owner.send("خالد")
        await owner.send("25")
        await owner.press("rc:method:cash")
        await owner.press("rc:skip")
        rows = database.conn.execute("SELECT kind, reason FROM receipts ORDER BY number").fetchall()
        next_month = month_label(add_months(today_kw().replace(day=1), 1))
        assert [tuple(r) for r in rows] == [
            ("deposit", "عربون عن شقة ٥ - عمارة ١٢ السالمية"),
            ("rent", f"إيجار عمارة ١٢ - شقة ٨ لشهر {next_month}"),
            ("sale", "دفعة بيع"),
            ("other", "رسوم عقد"),
        ]

        # ---------- إلغاء وتبديل وسط محادثة ----------
        await owner.send(BTN_RECEIPT)
        out = await owner.press("cancel")
        assert "تم الإلغاء" in texts(out)
        await owner.send(BTN_RECEIPT)
        out = await owner.send(BTN_TENANTS)  # زر قائمة ثاني ينهي السند ويفتح المستأجرين
        assert "ما فيه مستأجرين" in texts(out)
        out = await owner.send("نص عشوائي")
        assert not texts(out)  # السند انتهى فعلاً

        # ---------- المستأجرين ----------
        today = today_kw()
        tenants_input = [("أحمد السالم", "55112233", "عمارة ١٢ - شقة ٥", "350", "18", "no"),
                         ("سارة الفهد", "66554433", "عمارة ١٢ - شقة ٨", "420.250", "1", "yes")]
        for name, phone, unit, amount, day, paid in tenants_input:
            await owner.send(BTN_TENANTS)
            await owner.press("tn:add")
            for value in (name, phone, unit, amount, day):
                await owner.send(value)
            out = await owner.press(f"tn:paid:{paid}")
            assert "تمت إضافة" in texts(out)

        out = await owner.send(BTN_TENANTS)
        listing = texts(out)
        assert "✅ دفعوا: 1" in listing and "أحمد السالم" in str(out[-1].markup)
        ahmed = next(t for t in database.list_tenants(office.id) if t.name == "أحمد السالم")
        assert not ahmed.paid_for(today)

        # ---------- التذكير اليومي (بعد ٣ أيام من الاستحقاق) ----------
        due = due_date_in_month(today, 18)  # أحمد ما دفع الشهر الحالي، فالاستحقاق يوم ١٨ منه
        reminder_day = due - timedelta(days=3)
        before = len(tg.calls)
        assert await send_rent_reminders(app.bot, database, reminder_day) == 1
        sent = tg.calls[before:]
        recipients = {int(c.params["chat_id"]) for c in sent}
        assert recipients == {OWNER, AGENT}
        assert "يستحق بعد 3 أيام" in sent[0].text
        wa = unquote(sent[0].urls()[0])
        assert wa.startswith("https://wa.me/96555112233") and "أحمد السالم" in wa
        assert await send_rent_reminders(app.bot, database, reminder_day) == 0  # ما يكرر

        # ---------- تسجيل الدفع من زر التذكير ----------
        await owner.press(f"tn:pay:{ahmed.id}")
        out = await owner.press(f"tn:pm:{ahmed.id}:cash")
        docs = _files(out, "sendDocument")
        assert len(docs) == 1 and "سند قبض رقم 0005" in docs[0].text
        _save("receipt-rent.pdf", docs[0].files["document"][1])
        assert "wa.me/96555112233" in out[-1].urls()[0]
        ahmed = database.get_tenant(ahmed.id, office.id)
        assert ahmed.last_paid_month == month_key(due)

        # ---------- انتهاء الاشتراك والتجديد ----------
        database.conn.execute("UPDATE offices SET paid_until=? WHERE id=?",
                              ((today - timedelta(days=1)).isoformat(), office.id))
        database.conn.commit()
        out = await owner.send(BTN_CARD)
        assert "انتهى اشتراك" in texts(out) and "os:link" in out[-1].callback_data()
        out = await agent.send(BTN_RECEIPT)
        assert "تواصل مع صاحب المكتب" in texts(out)
        assert await send_rent_reminders(app.bot, database, today) == 0  # المكتب المنتهي ما يوصله تذكير

        # طلب رابط الدفع: يوصل للمدير، والمدير يلصق الرابط، ويوصل لصاحب المكتب
        out = await owner.press("os:link")
        to_admin = [c for c in out if str(c.params.get("chat_id")) == str(ADMIN)]
        assert "وصل طلبك" in texts(out) and to_admin and office.code in to_admin[0].text
        assert f"adm:link:{office.id}" in to_admin[0].callback_data()
        out = await owner.press("os:link")  # طلب مكرر خلال ١٠ دقايق ما يوصل للمدير
        assert not [c for c in out if str(c.params.get("chat_id")) == str(ADMIN)]
        await admin.press(f"adm:link:{office.id}")
        out = await admin.send("مو رابط")
        assert "هذا مو رابط" in texts(out)
        out = await admin.send("https://upay.example/link/abc123")
        to_owner = [c for c in out if str(c.params.get("chat_id")) == str(OWNER)]
        assert to_owner and "https://upay.example/link/abc123" in to_owner[0].text and "٢٤ ساعة" in to_owner[0].text
        assert "os:paid" in to_owner[0].callback_data() and "تم إرسال الرابط" in texts(out)
        out = await admin.send(f"/sendlink {office.code} https://upay.example/link/xyz")
        assert any("link/xyz" in c.text for c in out if str(c.params.get("chat_id")) == str(OWNER))
        out = await owner.press("os:link")  # بعد إرسال الرابط يقدر يطلب من جديد
        assert [c for c in out if str(c.params.get("chat_id")) == str(ADMIN)]
        out = await agent.send("/sendlink " + office.code + " https://evil.example")
        assert not texts(out)

        out = await owner.press("os:paid")
        to_admin = [c for c in out if str(c.params.get("chat_id")) == str(ADMIN)]
        assert to_admin and f"adm:act:{office.id}:1" in to_admin[0].callback_data()
        out = await admin.press(f"adm:act:{office.id}:1")
        assert any(str(c.params.get("chat_id")) == str(OWNER) and "تم تفعيل" in c.text for c in out)
        assert database.get_office(office.id).is_active()
        out = await owner.send(BTN_OFFICE)
        assert "✅ فعال" in texts(out)

        # الوسيط ما يقدر يفعّل أو يعدّل
        out = await agent.send("/activate " + office.code + " 12")
        assert not texts(out)

        # ---------- تقرير الإدارة وتنبيهات الاشتراك ----------
        out = await admin.send("/admin")
        assert "مكتب الديرة العقاري" in texts(out) and "بطاقات 2" in texts(out) and "سندات 5" in texts(out)
        paid_until = database.get_office(office.id).paid_until
        assert await send_subscription_notices(app.bot, database, cfg, paid_until - timedelta(days=3)) == 1
        assert await send_subscription_notices(app.bot, database, cfg, paid_until - timedelta(days=5)) == 0

    await renderer.stop()
    database.close()


def test_full_scenario():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(scenario(Path(tmp)))


def test_reminder_kind():
    from aqarbot.jobs import reminder_kind

    assert [reminder_kind(d) for d in (5, 3, 1, 0, -2, -3, -10, -11)] == \
        [None, "before", "before", "due", "due", "late", "late", None]


def test_next_unpaid_month():
    from aqarbot.db import Tenant
    from aqarbot.handlers.tenants import next_unpaid_month, status_icon

    t = Tenant(1, 1, "x", "965", "u", 1000, 10, "2026-09", True)
    assert next_unpaid_month(t, date(2026, 11, 5)) == date(2026, 10, 1)
    assert status_icon(t, date(2026, 11, 5)) == "🔴"  # عليه متأخرات من أكتوبر
    t.last_paid_month = "2026-10"
    assert status_icon(t, date(2026, 11, 5)) == "⏳"
    assert status_icon(t, date(2026, 11, 11)) == "🔴"
    t.last_paid_month = "2026-11"
    assert status_icon(t, date(2026, 11, 11)) == "✅"
