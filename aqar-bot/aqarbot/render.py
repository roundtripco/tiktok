"""تحويل قوالب HTML إلى صور وملفات PDF عن طريق متصفح Chromium (Playwright)."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

PKG_DIR = Path(__file__).resolve().parent
FONTS_DIR = PKG_DIR / "fonts"

_env = Environment(
    loader=FileSystemLoader(PKG_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
)


def data_uri(content: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


def file_data_uri(path: str | Path | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return data_uri(Path(path).read_bytes(), mime)


@lru_cache(maxsize=1)
def fonts_css() -> str:
    """خط Tajawal مضمّن داخل الصفحة (عربي + لاتيني)."""
    ranges = {
        "arabic": "U+0600-06FF, U+0750-077F, U+0870-088E, U+0890-0891, U+0897-08E1, U+08E3-08FF,"
                  " U+200C-200E, U+2010-2011, U+204F, U+2E41, U+FB50-FDFF, U+FE70-FE74, U+FE76-FEFC",
        "latin": "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308,"
                 " U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    }
    rules = []
    for weight in (400, 700, 800):
        for subset, unicode_range in ranges.items():
            font = (FONTS_DIR / f"tajawal-{subset}-{weight}-normal.woff2").read_bytes()
            rules.append(
                "@font-face{font-family:'Tajawal';font-style:normal;font-display:block;"
                f"font-weight:{weight};src:url({data_uri(font, 'font/woff2')}) format('woff2');"
                f"unicode-range:{unicode_range};}}"
            )
    return "\n".join(rules)


def render_html(template: str, **context) -> str:
    return _env.get_template(template).render(fonts_css=fonts_css(), **context)


class Renderer:
    """متصفح واحد يبقى شغال طول عمر البوت، وكل طلب يفتح صفحة جديدة."""

    def __init__(self, max_parallel: int = 2):
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_parallel)

    async def _ensure_browser(self):
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                from playwright.async_api import async_playwright

                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(args=["--no-sandbox"])
        return self._browser

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _open(self, html: str, width: int, height: int):
        browser = await self._ensure_browser()
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.set_content(html, wait_until="load")
        await page.evaluate("document.fonts.ready.then(() => true)")
        return page

    async def image(self, html: str, width: int, height: int) -> bytes:
        async with self._sem:
            page = await self._open(html, width, height)
            try:
                return await page.screenshot(type="jpeg", quality=92)
            finally:
                await page.close()

    async def pdf(self, html: str, width: str, height: str, viewport: tuple[int, int] = (1080, 1350)) -> bytes:
        async with self._sem:
            page = await self._open(html, *viewport)
            try:
                return await page.pdf(
                    width=width, height=height, print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            finally:
                await page.close()
