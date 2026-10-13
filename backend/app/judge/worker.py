import logging
import time

from app.judge.config import WORKER_POLL_SECONDS
from app.services import judge_service

logger = logging.getLogger("app.judge.worker")


def run_worker() -> None:
    logger.info("C++17 judge worker started")
    while True:
        try:
            recovered = judge_service.recover_stale_submissions()
            if recovered:
                logger.warning("Recovered stale coding submissions: count=%s", recovered)
            submission = judge_service.claim_submission()
            if submission is None:
                time.sleep(WORKER_POLL_SECONDS)
                continue
            judge_service.process_submission(submission)
        except KeyboardInterrupt:
            logger.info("C++17 judge worker stopping")
            return
        except Exception:
            logger.exception("Judge worker poll failed")
            time.sleep(WORKER_POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
