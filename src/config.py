"""Load API credentials from .env file."""

import os
from dotenv import load_dotenv

# Load variables from .env file (located next to this file)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


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