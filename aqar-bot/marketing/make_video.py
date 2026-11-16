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
DURATION = 33
OUT = ROOT / "marketing" / "out"
VOICE_DIR = ROOT / "marketing" / "voice"
# (اسم الملف، يبدأ عند، أقصى مدة) بالثواني — نفس الجدول في voiceover.md
VOICE_CUES = [("1.mp3", 0.2, 2.7), ("2.mp3", 3.2, 11.0), ("3.mp3", 14.6, 7.6), ("4.mp3", 22.6, 5.6), ("5.mp3", 28.6, 4.2)]
MAX_SPEEDUP = 1.15


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def add_voiceover(video: Path, target: Path) -> bool:
    """يدمج ملفات التعليق الصوتي إذا موجودة. يرجع False إذا ما فيه ملفات."""
    cues = [(VOICE_DIR / name, start, limit) for name, start, limit in VOICE_CUES]
    present = [c for c in cues if c[0].exists()]
    if not present:
        return False
    missing = [c[0].name for c in cues if not c[0].exists()]
    if missing:
        print("⚠️ ملفات ناقصة (الفيديو بيطلع بدونها):", ", ".join(missing))
    inputs, filters = [], [f"anullsrc=r=44100:cl=stereo,atrim=0:{DURATION}[base]"]
    for idx, (path, start, limit) in enumerate(present):
        length = audio_duration(path)
        speed = max(1.0, length / limit)
        if speed > MAX_SPEEDUP:
            raise SystemExit(f"❌ {path.name} مدته {length:.1f} ث وأقصى شي {limit} ث. اختصر الجملة وولّدها من جديد.")
        inputs += ["-i", str(path)]
        delay = int(start * 1000)
        filters.append(
            f"[{idx}:a]asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
            f"atempo={speed:.3f},adelay={delay}|{delay}[a{idx}]"
        )
    labels = "[base]" + "".join(f"[a{i}]" for i in range(len(present)))
    filters.append(f"{labels}amix=inputs={len(present) + 1}:duration=first:normalize=0[aout]")
    track = target.with_suffix(".wav")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
         "-map", "[aout]", str(track)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(track), "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", str(DURATION), "-movflags", "+faststart", str(target)],
        check=True,
    )
    track.unlink()
    return True


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
            if i in (int(2 * FPS), int(13.5 * FPS), int(19.5 * FPS), int(21.5 * FPS), int(27 * FPS), int(31 * FPS)):
                (OUT / f"frame-{t:04.1f}s.jpg").write_bytes(frame)
        await browser.close()
    ffmpeg.stdin.close()
    if ffmpeg.wait() != 0:
        raise SystemExit("ffmpeg فشل")
    print("✅", target)
    voiced = OUT / "demo-voice.mp4"
    if add_voiceover(target, voiced):
        print("🔊", voiced)


if __name__ == "__main__":
    asyncio.run(main())
