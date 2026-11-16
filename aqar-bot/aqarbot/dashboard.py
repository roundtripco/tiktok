"""لوحة تحكم المدير على المتصفح: المكاتب، الاشتراكات، الطلبات المعلّقة، والدخل.

الدخول: المدير يكتب /dashboard في البوت، ويوصله رابط دخول صالح ١٥ دقيقة لمرة وحدة.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape
from telegram.error import TelegramError
from telegram.ext import Application

from .config import Config
from .db import Database, Office
from .documents import COLORS
from .render import file_data_uri, fonts_css
from .utils import add_months, display_phone, format_date, format_kwd, month_label, today_kw

log = logging.getLogger(__name__)

LOGIN_TTL = 15 * 60
SESSION_TTL = 7 * 24 * 3600
COOKIE = "aqar_session"
STATUS_LABELS = {"paid": "مشترك", "trial": "تجربة", "expired": "منتهي"}

_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates" / "dashboard"),
    autoescape=select_autoescape(["html"]),
)


def ago(created: str | datetime) -> str:
    when = datetime.fromisoformat(created) if isinstance(created, str) else created
    minutes = int((datetime.now() - when).total_seconds() // 60)
    if minutes < 1:
        return "الحين"
    if minutes < 60:
        return f"قبل {minutes} دقيقة"
    if minutes < 24 * 60:
        return f"قبل {minutes // 60} ساعة"
    return f"قبل {minutes // (24 * 60)} يوم"


def office_status(office: Office, stats: dict, today: date) -> str:
    if not office.is_active(today):
        return "expired"
    return "paid" if stats.get("payments") else "trial"


class Dashboard:
    def __init__(self, tg: Application):
        self.tg = tg
        self._logins: dict[str, float] = {}
        self._sessions: dict[str, dict] = {}
        self._runner: web.AppRunner | None = None
        self.port: int | None = None
        app = web.Application(middlewares=[self._auth])
        app.add_routes([
            web.get("/login", self.login),
            web.get("/logout", self.logout),
            web.get("/", self.overview),
            web.get("/office/{id:\\d+}", self.office_page),
            web.post("/office/{id:\\d+}/activate", self.activate),
            web.post("/office/{id:\\d+}/trial", self.trial),
            web.post("/office/{id:\\d+}/link", self.send_link),
            web.post("/office/{id:\\d+}/message", self.message),
            web.post("/broadcast", self.broadcast),
        ])
        self.web = app

    # ---------- الخدمات ----------

    @property
    def db(self) -> Database:
        return self.tg.bot_data["db"]

    @property
    def cfg(self) -> Config:
        return self.tg.bot_data["config"]

    # ---------- التشغيل ----------

    async def start(self, host: str = "0.0.0.0", port: int | None = None) -> None:
        self._runner = web.AppRunner(self.web, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, self.cfg.dashboard_port if port is None else port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        log.info("لوحة التحكم شغالة على المنفذ %s", self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def login_link(self) -> str:
        now = time.time()
        self._logins = {t: exp for t, exp in self._logins.items() if exp > now}
        token = secrets.token_urlsafe(24)
        self._logins[token] = now + LOGIN_TTL
        return f"{self.cfg.dashboard_url}/login?t={token}"

    # ---------- الحماية ----------

    def _page(self, template: str, request: web.Request | None = None, **context) -> web.Response:
        session = request.get("session") if request is not None else None
        html = _env.get_template(template).render(
            fonts_css=fonts_css(), service_name=self.cfg.service_name,
            csrf=session["csrf"] if session else "", flash=request.query.get("ok") if request else None,
            error=request.query.get("err") if request else None, **context,
        )
        return web.Response(text=html, content_type="text/html")

    def _denied(self, status: int = 401) -> web.Response:
        response = self._page("denied.html")
        response.set_status(status)
        return response

    @web.middleware
    async def _auth(self, request: web.Request, handler):
        if request.path == "/login":
            return await handler(request)
        session = self._sessions.get(request.cookies.get(COOKIE, ""))
        if not session or session["exp"] < time.time():
            return self._denied()
        request["session"] = session
        if request.method == "POST":
            form = await request.post()
            if not secrets.compare_digest(str(form.get("csrf", "")), session["csrf"]):
                return self._denied(403)
            request["form"] = form
        return await handler(request)

    async def login(self, request: web.Request) -> web.Response:
        exp = self._logins.pop(request.query.get("t", ""), None)
        if not exp or exp < time.time():
            return self._denied()
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = {"exp": time.time() + SESSION_TTL, "csrf": secrets.token_urlsafe(24)}
        response = web.HTTPFound("/")
        response.set_cookie(COOKIE, sid, max_age=SESSION_TTL, httponly=True, samesite="Strict")
        return response

    async def logout(self, request: web.Request) -> web.Response:
        self._sessions.pop(request.cookies.get(COOKIE, ""), None)
        response = self._denied(200)
        response.del_cookie(COOKIE)
        return response

    # ---------- البيانات ----------

    def _rows(self, today: date) -> list[dict]:
        stats = self.db.office_stats(today - timedelta(days=30))
        rows = []
        for office in self.db.list_offices():
            s = stats.get(office.id, {})
            status = office_status(office, s, today)
            rows.append({
                "id": office.id, "name": office.name, "code": office.code,
                "phone": display_phone(office.phone), "status": status, "status_label": STATUS_LABELS[status],
                "paid_until": format_date(office.paid_until), "days_left": office.days_left(today),
                "members": s.get("members", 0), "tenants": s.get("tenants", 0),
                "cards": s.get("cards", 0), "receipts": s.get("receipts", 0),
                "last_active": format_date(date.fromisoformat(s["last_active"])) if s.get("last_active") else "—",
                "revenue": format_kwd(s["revenue"]) if s.get("revenue") else "—",
                "created": format_date(datetime.fromisoformat(s["created_at"]).date()) if s.get("created_at") else "—",
            })
        return rows

    def _office_or_404(self, request: web.Request) -> Office:
        office = self.db.get_office(int(request.match_info["id"]))
        if office is None:
            raise web.HTTPNotFound()
        return office

    @staticmethod
    def _back(path: str, *, ok: str | None = None, err: str | None = None) -> web.HTTPFound:
        if ok:
            return web.HTTPFound(f"{path}?ok={quote(ok)}")
        return web.HTTPFound(f"{path}?err={quote(err or '')}")

    # ---------- الصفحات ----------

    async def overview(self, request: web.Request) -> web.Response:
        today = today_kw()
        rows = self._rows(today)
        by_id = {r["id"]: r for r in rows}
        month_start = today.replace(day=1)
        month_revenue = self.db.revenue_between(month_start, add_months(month_start, 1))
        active = [r for r in rows if r["status"] != "expired"]
        paying = [r for r in rows if r["status"] == "paid"]
        requests = [
            {**req, "office": by_id[req["office_id"]], "ago": ago(req["created_at"]),
             "label": "يطلب رابط دفع" if req["kind"] == "link" else "يقول إنه دفع"}
            for req in self.db.open_requests() if req["office_id"] in by_id
        ]
        expiring = sorted((r for r in active if r["days_left"] <= 7), key=lambda r: r["days_left"])
        return self._page(
            "overview.html", request,
            rows=rows, requests=requests, expiring=expiring, month=month_label(today),
            kpi={
                "total": len(rows), "active": len(active), "paying": len(paying),
                "trial": sum(r["status"] == "trial" for r in rows),
                "expired": sum(r["status"] == "expired" for r in rows),
                "month_revenue": format_kwd(month_revenue) if month_revenue else "0 د.ك",
                "mrr": f"{len(paying) * self.cfg.price_kwd} د.ك",
            },
            price=self.cfg.price_kwd,
        )

    async def office_page(self, request: web.Request) -> web.Response:
        office = self._office_or_404(request)
        today = today_kw()
        row = next(r for r in self._rows(today) if r["id"] == office.id)
        tenants = self.db.list_tenants(office.id)
        unpaid = [t for t in tenants if not t.paid_for(today)]
        history = [{
            "date": format_date(datetime.fromisoformat(a["created_at"]).date()),
            "what": f"اشتراك {a['months']} شهر" if a["kind"] == "paid" else f"تمديد تجربة {a['days']} يوم",
            "amount": format_kwd(a["amount_fils"]) if a["amount_fils"] else "—",
            "until": format_date(date.fromisoformat(a["new_paid_until"])),
        } for a in self.db.activations(office.id)]
        open_reqs = [
            {"label": "يطلب رابط دفع" if r["kind"] == "link" else "يقول إنه دفع", "ago": ago(r["created_at"])}
            for r in self.db.open_requests() if r["office_id"] == office.id
        ]
        return self._page(
            "office.html", request,
            office=office, row=row, color=COLORS.get(office.color, COLORS["navy"]),
            logo=file_data_uri(office.logo_path), members=self.db.list_members(office.id),
            tenants_count=len(tenants), unpaid_count=len(unpaid),
            unpaid_total=format_kwd(sum(t.amount_fils for t in unpaid)) if unpaid else "0 د.ك",
            history=history, open_reqs=open_reqs, price=self.cfg.price_kwd,
        )

    # ---------- الإجراءات ----------

    async def _notify(self, chat_id: int, text: str, **kwargs) -> bool:
        try:
            await self.tg.bot.send_message(chat_id, text, **kwargs)
            return True
        except TelegramError as exc:
            log.warning("تعذر الإرسال إلى %s: %s", chat_id, exc)
            return False

    async def activate(self, request: web.Request) -> web.Response:
        from .handlers.office import notify_activation

        office = self._office_or_404(request)
        months = int(request["form"].get("months", "0") or 0)
        if months not in (1, 3, 6, 12):
            raise self._back(f"/office/{office.id}", err="مدة غير صحيحة")
        admin_id = min(self.cfg.admin_ids) if self.cfg.admin_ids else 0
        office = self.db.extend_subscription(office.id, months, admin_id, months * self.cfg.price_kwd * 1000)
        try:
            await notify_activation(self.tg.bot, office)
        except TelegramError as exc:
            log.warning("تعذر تنبيه المكتب: %s", exc)
        raise self._back(f"/office/{office.id}", ok=f"تم التفعيل لين {format_date(office.paid_until)}")

    async def trial(self, request: web.Request) -> web.Response:
        office = self._office_or_404(request)
        days = int(request["form"].get("days", "0") or 0)
        if days not in (3, 7, 14):
            raise self._back(f"/office/{office.id}", err="عدد أيام غير صحيح")
        admin_id = min(self.cfg.admin_ids) if self.cfg.admin_ids else 0
        office = self.db.extend_trial(office.id, days, admin_id)
        await self._notify(
            office.owner_id,
            f"🎁 تم تمديد تجربة <b>{escape(office.name)}</b> {days} أيام، لين {format_date(office.paid_until)}.",
        )
        raise self._back(f"/office/{office.id}", ok=f"تم تمديد التجربة لين {format_date(office.paid_until)}")

    async def send_link(self, request: web.Request) -> web.Response:
        from .handlers.office import URL_RE, send_link_to_office

        office = self._office_or_404(request)
        url = str(request["form"].get("url", "")).strip()
        if not URL_RE.match(url):
            raise self._back(f"/office/{office.id}", err="الرابط لازم يبدأ بـ https://")
        try:
            await send_link_to_office(self.tg.bot, self.cfg, self.db, office, url)
        except TelegramError:
            raise self._back(f"/office/{office.id}", err="ما قدرنا نرسل الرابط، يمكن المكتب حظر البوت")
        raise self._back(f"/office/{office.id}", ok="تم إرسال رابط الدفع")

    async def message(self, request: web.Request) -> web.Response:
        office = self._office_or_404(request)
        text = str(request["form"].get("text", "")).strip()
        if not text:
            raise self._back(f"/office/{office.id}", err="الرسالة فاضية")
        sent = await self._notify(office.owner_id, f"📩 رسالة من {escape(self.cfg.service_name)}:\n\n{escape(text)}")
        if not sent:
            raise self._back(f"/office/{office.id}", err="ما وصلت الرسالة، يمكن المكتب حظر البوت")
        raise self._back(f"/office/{office.id}", ok="تم إرسال الرسالة")

    async def broadcast(self, request: web.Request) -> web.Response:
        form = request["form"]
        text = str(form.get("text", "")).strip()
        audience = str(form.get("audience", "active"))
        if not text:
            raise self._back("/", err="الرسالة فاضية")
        today = today_kw()
        stats = self.db.office_stats(today)
        targets = [
            o for o in self.db.list_offices()
            if audience == "all" or office_status(o, stats.get(o.id, {}), today) == audience
            or (audience == "active" and o.is_active(today))
        ]
        sent = 0
        for office in targets:
            sent += await self._notify(office.owner_id, f"📢 {escape(text)}")
            await asyncio.sleep(0.05)
        raise self._back("/", ok=f"وصلت الرسالة لـ {sent} من {len(targets)} مكتب")
