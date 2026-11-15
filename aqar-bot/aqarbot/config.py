"""إعدادات البوت من متغيرات البيئة أو ملف .env"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: frozenset[int]
    data_dir: Path
    service_name: str
    upay_link: str
    price_kwd: int
    trial_days: int
    reminder_hour: int
    support_contact: str


def load_config() -> Config:
    _load_dotenv(PROJECT_DIR / ".env")
    token = os.environ.get("BOT_TOKEN", "")
    if not token:
        raise SystemExit("BOT_TOKEN غير موجود. انسخ .env.example إلى .env وعبّئه.")
    admin_ids = frozenset(
        int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
    )
    data_dir = Path(os.environ.get("DATA_DIR", PROJECT_DIR / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        token=token,
        admin_ids=admin_ids,
        data_dir=data_dir,
        service_name=os.environ.get("SERVICE_NAME", "مساعد المكتب العقاري"),
        upay_link=os.environ.get("UPAY_LINK", ""),
        price_kwd=int(os.environ.get("PRICE_KWD", "12")),
        trial_days=int(os.environ.get("TRIAL_DAYS", "14")),
        reminder_hour=int(os.environ.get("REMINDER_HOUR", "9")),
        support_contact=os.environ.get("SUPPORT_CONTACT", ""),
    )
