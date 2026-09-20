from __future__ import annotations

import logging
import time

from onetake_api.config import get_settings
from onetake_api.platform.queue import get_queue

logger = logging.getLogger(__name__)


def enqueue_media_cleanup() -> None:
    get_queue("maintenance").enqueue(
        "onetake_api.modules.maintenance.tasks.run_media_cleanup",
        job_timeout=300,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    interval = max(60, get_settings().media_cleanup_interval_seconds)
    while True:
        try:
            enqueue_media_cleanup()
        except Exception:
            logger.exception("提交媒体生命周期清理任务失败")
        time.sleep(interval)


if __name__ == "__main__":
    main()