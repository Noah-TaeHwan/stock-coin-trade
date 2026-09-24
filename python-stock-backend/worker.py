"""Background job process: runs the APScheduler jobs outside the web server.

Before this split every gunicorn worker process imported app.py and started
its own scheduler. Running the jobs here keeps exactly one copy of them no
matter how the web tier is scaled.

    python worker.py
"""

from settings import load_env_file

load_env_file()

import logging  # noqa: E402

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402

from scheduler import build_scheduler  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scheduler = build_scheduler(BlockingScheduler)
    for job in scheduler.get_jobs():
        logging.getLogger("worker").info("scheduled %s (%s)", job.name, job.trigger)
    scheduler.start()


if __name__ == "__main__":
    main()
