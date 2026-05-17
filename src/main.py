"""
Test script for Groww API connection.

Usage:
    python src/main.py

This script will:
  1. Load API credentials from .env (via config.py)
  2. Generate a TOTP from the secret (if provided)
  3. Call get_access_token() to authenticate
  4. Print the access token on success
"""

import sys

from src.config import get_groww_credentials
from growwapi import GrowwAPI
import pyotp


def main():
    creds = get_groww_credentials()

    api_key = creds["GROWW_API_KEY"]
    secret = creds["GROWW_API_SECRET"]

    # Check if placeholders are still in use
    if api_key == "YOUR_API_KEY" or not api_key:
        print(
            "❌  ERROR: Please update GROWW_API_KEY and GROWW_API_SECRET in the .env file."
        )
        sys.exit(1)

    print("🔑  Attempting to get Groww access token...")

    # If 'secret' is a TOTP-compatible key (base32), generate a TOTP
    # Otherwise pass it directly as 'secret' parameter
    try:
        response = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
    
    except Exception as e:
        print(f"❌  Failed to get access token: {e}")
        sys.exit(1)

    API_AUTH_TOKEN = response
 
    # Initialize Groww API
    groww = GrowwAPI(API_AUTH_TOKEN)
    
    quote_response = groww.get_quote(
        exchange=groww.EXCHANGE_NSE,
        segment=groww.SEGMENT_CASH,
        trading_symbol="NIFTY"
    )
    print(quote_response)


if __name__ == "__main__":
    main()