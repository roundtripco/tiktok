"""يصنع الفيديو التعريفي (عمودي 1080×1920، ٣٠ ثانية) من عينات البوت الحقيقية.

التشغيل من مجلد aqar-bot:
    AQAR_SAMPLES_DIR=samples python -m pytest     # يجهّز البطاقة والسند أول مرة
    python marketing/make_video.py                 # يطلّع marketing/out/demo.mp4
"""

from __future__ import annotations

import asyncio
import io
import subprocess
import sys
from pathlib import Path

import pypdfium2 as pdfium
from jinja2 import Template

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aqarbot.render import Renderer, data_uri, fonts_css  # noqa: E402
from tests.scenes import make_images  # noqa: E402

FPS = 30
DURATION = 30
OUT = ROOT / "marketing" / "out"


def pdf_to_png(path: Path, scale: float = 2.2) -> bytes:
    image = pdfium.PdfDocument(str(path))[0].render(scale=scale).to_pil()
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    renderer = Renderer()
    scenes, _ = await make_images(renderer)
    await renderer.stop()

    html = Template((ROOT / "marketing" / "video.html").read_text(encoding="utf-8")).render(
        fonts_css=fonts_css(),
        service_name="مساعد المكتب العقاري",
        trial_days=14,
        price=12,
        cta="👆 الرابط في البايو",
        photos=[data_uri(scenes[k]) for k in ("living", "kitchen", "bedroom", "building")],
        card=data_uri((ROOT / "samples" / "card-rent.jpg").read_bytes()),
        receipt=data_uri(pdf_to_png(ROOT / "samples" / "receipt.pdf"), "image/png"),
    )

    from playwright.async_api import async_playwright

    target = OUT / "demo.mp4"
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(target)],
        stdin=subprocess.PIPE,
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1080, "height": 1920})
        await page.set_content(html, wait_until="load")
        await page.evaluate("document.fonts.ready.then(() => true)")
        for i in range(FPS * DURATION):
            t = i / FPS
            await page.evaluate(f"render({t})")
            frame = await page.screenshot(type="jpeg", quality=95)
            ffmpeg.stdin.write(frame)
            if i in (int(2 * FPS), int(13.5 * FPS), int(19 * FPS), int(24 * FPS), int(28 * FPS)):
                (OUT / f"frame-{t:04.1f}s.jpg").write_bytes(frame)
        await browser.close()
    ffmpeg.stdin.close()
    if ffmpeg.wait() != 0:
        raise SystemExit("ffmpeg فشل")
    print("✅", target)


if __name__ == "__main__":
    asyncio.run(main())
