"""تشغيل البوت: python -m aqarbot"""

import logging

from telegram import Update

from .app import build_application
from .config import load_config
from .db import Database
from .render import Renderer


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    app = build_application(cfg, Database(cfg.data_dir / "aqarbot.db"), Renderer())
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
