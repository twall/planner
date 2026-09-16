"""Standalone entry point for seeding a task's prompt in the background.

launch_session used to block attach on this succeeding (up to 60s of
waiting for claude's composer to become ready). That's a bad trade: attach
doesn't actually depend on it, and the parent planner process exits the
moment attach happens anyway, so there's nothing to await it in-process.
Run it as a detached subprocess instead — it keeps trying independently
of planner's own lifetime, and logs to the same log file on failure.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planner.config import LOG_PATH
from planner.backends import get_backend
from planner.session_manager import _send_commands


def main() -> None:
    full_name, prompt = sys.argv[1], sys.argv[2]
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    backend = get_backend()
    if not _send_commands(backend, full_name, prompt, auto_submit=False):
        logging.getLogger(__name__).error(
            "inject_prompt: session %s never became ready; prompt not sent", full_name
        )


if __name__ == "__main__":
    main()
