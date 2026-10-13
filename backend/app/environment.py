"""Load backend-local environment settings from a stable project path."""

from pathlib import Path

from dotenv import load_dotenv

BACKEND_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_environment() -> None:
    load_dotenv(dotenv_path=BACKEND_ENV_FILE, override=False)
