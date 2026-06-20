"""Load API credentials from .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from the project-root .env (the gitignored file that holds the
# real keys). This file is <root>/src/config.py, so the repo root is one level up.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def get_groww_credentials() -> dict:
    """
    Returns the Groww API key and secret from environment variables.

    Returns:
        dict: Contains 'GROWW_API_KEY' and 'GROWW_API_SECRET'
    """
    return {
        "GROWW_API_KEY": os.getenv("GROWW_API_KEY", ""),
        "GROWW_API_SECRET": os.getenv("GROWW_API_SECRET", ""),
    }