"""تجربة لوحة التحكم: الدخول برابط مؤقت، الصفحات، الإجراءات، والحماية."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from datetime import timedelta
from pathlib import Path

import aiohttp

from aqarbot.app import build_application
from aqarbot.config import Config
from aqarbot.db import Database
from aqarbot.render import Renderer
from aqarbot.utils import today_kw

from .fake_telegram import Client, FakeTelegram, texts

ADMIN = 9999


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def scenario(data_dir: Path) -> None:
    cfg = Config(
        token="123:TEST", admin_ids=frozenset({ADMIN}), data_dir=data_dir, service_name="مساعد المكتب العقاري",
        upay_link="", price_kwd=12, trial_days=14, reminder_hour=9, support_contact="",
        dashboard_url="http://127.0.0.1", dashboard_port=0,
    )
    database = Database(data_dir / "dash.db")
    renderer = Renderer()
    tg = FakeTelegram()
    app = build_application(cfg, database, renderer, request=tg)
    today = today_kw()

    # ثلاث مكاتب: مشترك، تجربة طلب رابط، منتهي
    paid = database.create_office(name="مكتب الديرة العقاري", phone="96599887766", color="green", logo_path=None,
                                  owner_id=101, owner_name="عبدالله", trial_days=14)
    database.extend_subscription(paid.id, 1, ADMIN, 12_000)
    trial = database.create_office(name="مكتب السالمية", phone="96555443322", color="navy", logo_path=None,
                                   owner_id=102, owner_name="فهد", trial_days=14)
    database.add_request(trial.id, "link")
    expired = database.create_office(name="مكتب حولي للعقار", phone="96566778899", color="maroon", logo_path=None,
                                     owner_id=103, owner_name="سارة", trial_days=14)
    database.conn.execute("UPDATE offices SET paid_until=? WHERE id=?", ((today - timedelta(days=2)).isoformat(), expired.id))
    database.conn.commit()
    for _ in range(5):
        database.log_usage(paid.id, "card")
    database.log_usage(paid.id, "receipt")
    database.add_tenant(office_id=paid.id, name="أحمد", phone="96555112233", unit="شقة ٥", amount_fils=350_000,
                        due_day=18, last_paid_month=None)

    async with app:
        dashboard = app.bot_data["dashboard"]
        await dashboard.start(host="127.0.0.1", port=0)
        base = f"http://127.0.0.1:{dashboard.port}"
        admin = Client(app, tg, ADMIN, "المدير")
        stranger = Client(app, tg, 555, "غريب")

        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar) as http:
            # بدون دخول
            async with http.get(base + "/") as r:
                assert r.status == 401 and "/dashboard" in await r.text()

            # رابط الدخول للمدير فقط
            assert not texts(await stranger.send("/dashboard"))
            out = await admin.send("/dashboard")
            link = re.search(r"http://127\.0\.0\.1/login\?t=(\S+)", texts(out))
            assert link, texts(out)
            token = link.group(1)
            async with http.get(f"{base}/login?t=wrong", allow_redirects=False) as r:
                assert r.status == 401
            async with http.get(f"{base}/login?t={token}", allow_redirects=False) as r:
                assert r.status == 302
            async with aiohttp.ClientSession() as other:  # نفس الرابط ما يشتغل مرة ثانية
                async with other.get(f"{base}/login?t={token}", allow_redirects=False) as r:
                    assert r.status == 401

            # الصفحة الرئيسية
            async with http.get(base + "/") as r:
                html = await r.text()
            assert r.status == 200
            for name in ("مكتب الديرة العقاري", "مكتب السالمية", "مكتب حولي للعقار"):
                assert name in html
            assert "يطلب رابط دفع" in html and "12 د.ك" in html
            overview_html = html
            csrf = _csrf(html)

            # حماية: طلب بدون csrf مرفوض
            async with http.post(f"{base}/office/{trial.id}/link", data={"url": "https://x.example"}) as r:
                assert r.status == 403

            # إرسال رابط دفع
            before = len(tg.calls)
            async with http.post(f"{base}/office/{trial.id}/link",
                                 data={"csrf": csrf, "url": "https://upay.example/l/1"}) as r:
                assert "تم إرسال رابط الدفع" in await r.text()
            sent = tg.calls[before:]
            assert any(c.params.get("chat_id") in (102, "102") and "upay.example/l/1" in c.text for c in sent)
            assert not database.open_requests()

            async with http.post(f"{base}/office/{trial.id}/link", data={"csrf": csrf, "url": "مو رابط"}) as r:
                assert "https://" in await r.text()

            # تفعيل اشتراك
            async with http.post(f"{base}/office/{trial.id}/activate", data={"csrf": csrf, "months": "3"}) as r:
                assert "تم التفعيل" in await r.text()
            assert database.get_office(trial.id).days_left() > 80
            assert database.revenue_between(today.replace(day=1), today + timedelta(days=40)) == 12_000 + 36_000

            # تمديد تجربة المكتب المنتهي
            async with http.post(f"{base}/office/{expired.id}/trial", data={"csrf": csrf, "days": "7"}) as r:
                assert "تم تمديد التجربة" in await r.text()
            assert database.get_office(expired.id).days_left() == 7

            # رسالة لمكتب، ورسالة جماعية
            before = len(tg.calls)
            async with http.post(f"{base}/office/{paid.id}/message", data={"csrf": csrf, "text": "هلا <b>"}) as r:
                assert "تم إرسال الرسالة" in await r.text()
            assert "&lt;b&gt;" in tg.calls[before].text  # النص ينهرب
            async with http.post(f"{base}/broadcast", data={"csrf": csrf, "text": "ميزة جديدة", "audience": "all"}) as r:
                assert "وصلت الرسالة لـ 3 من 3" in await r.text()

            # صفحة المكتب
            async with http.get(f"{base}/office/{paid.id}") as r:
                office_html = await r.text()
            assert "اشتراك 1 شهر" in office_html and "350 د.ك" in office_html
            async with http.get(f"{base}/office/999") as r:
                assert r.status == 404

            async with http.get(base + "/logout") as r:
                assert r.status == 200
            async with http.get(base + "/") as r:
                assert r.status == 401

        await dashboard.stop()

    out = os.environ.get("AQAR_SAMPLES_DIR")
    if out:
        for name, html in (("dashboard.png", overview_html), ("dashboard-office.png", office_html)):
            browser = await renderer._ensure_browser()
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await page.set_content(html, wait_until="load")
            await page.screenshot(path=str(Path(out, name)), full_page=True)
            await page.close()
    await renderer.stop()
    database.close()


def test_dashboard():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(scenario(Path(tmp)))
