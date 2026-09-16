"""RQ worker entrypoint.

Two queues, deliberately:

  default  short work - cross-checks, perceptual hashing, grade computation
  slow     ICR extraction, vision inference, price computation, training

They are separated so a backlog of slow vision calls cannot starve the quick
cross-checks a reviewer is waiting on. Both are served by this process in dev;
in production they are separate deployments with different replica counts.
"""

from __future__ import annotations

import signal
import sys
from types import FrameType

from redis import Redis
from rq import Queue, Worker

from app.config import get_settings
from app.logging_config import configure_logging, get_logger

settings = get_settings()
logger = get_logger(__name__)

_shutting_down = False


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    """Finish the current job, then stop.

    RQ's default SIGTERM handling already warm-shuts-down, but an ICR or
    vision job can run for a minute or more and a hard kill loses the work
    plus leaves a `running` row in `job_runs` that nothing ever closes.
    """
    global _shutting_down
    if _shutting_down:
        logger.warning("worker_force_exit", signal=signum)
        sys.exit(1)
    _shutting_down = True
    logger.info("worker_shutdown_requested", signal=signum)


def main() -> int:
    configure_logging()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    connection = Redis.from_url(settings.redis_url)
    queues = [
        Queue(settings.rq_queue_default, connection=connection),
        Queue(settings.rq_queue_slow, connection=connection),
    ]

    logger.info(
        "worker_started",
        queues=[q.name for q in queues],
        environment=settings.environment,
        job_timeout=settings.rq_job_timeout_seconds,
    )

    worker = Worker(queues, connection=connection, name=None)
    # `with_scheduler` runs RQ's scheduler in-process so retry backoff and the
    # cron-style jobs (anchor recompute, PDP purge) fire without a second
    # component to deploy.
    worker.work(with_scheduler=True, logging_level=settings.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
