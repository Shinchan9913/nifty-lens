"""
Test script for Groww API connection — tests all major endpoints.

Usage:
    python src/main.py

This script will:
  1. Load API credentials from .env (via config.py)
  2. Authenticate with Groww
  3. Print raw responses from: get_quote, get_ltp, get_ohlc,
     get_historical_candles, get_holdings_for_user, get_positions_for_user,
     get_available_margin_details, get_user_profile
"""

import sys
import os
from datetime import datetime, timedelta

# Add project root to Python path so 'src' package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_groww_credentials
from growwapi import GrowwAPI
import pyotp


def print_separator(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main():
    creds = get_groww_credentials()

    api_key = creds["GROWW_API_KEY"]
    secret = creds["GROWW_API_SECRET"]

    if api_key == "YOUR_API_KEY" or not api_key:
        print(
            "❌  ERROR: Please update GROWW_API_KEY and GROWW_API_SECRET in the .env file."
        )
        sys.exit(1)

    print("🔑  Attempting to get Groww access token...")
    try:
        token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
        print(f"✅  Token obtained (first 20 chars): {token[:20]}...")
    except Exception as e:
        print(f"❌  Failed to get access token: {e}")
        sys.exit(1)

    groww = GrowwAPI(token)

    # ─────────────────────────────────────────────────
    # 1. get_quote — single symbol snapshot
    # ─────────────────────────────────────────────────
    print_separator("1. get_quote() — NIFTY snapshot")
    try:
        quote = groww.get_quote(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            trading_symbol="NIFTY",
        )
        print(f"Type: {type(quote).__name__}")
        print(f"Keys: {list(quote.keys())}")
        print(f"Payload: {quote}")
    except Exception as e:
        print(f"❌  get_quote failed: {e}")

    # ─────────────────────────────────────────────────
    # 2. get_ltp — last traded price for batch
    # ─────────────────────────────────────────────────
    print_separator("2. get_ltp() — LTP for NIFTY, BANKNIFTY, RELIANCE")
    try:
        ltp = groww.get_ltp(
            exchange_trading_symbols=("NSE_NIFTY", "NSE_BANKNIFTY", "NSE_RELIANCE"),
            segment=groww.SEGMENT_CASH,
        )
        print(f"Type: {type(ltp).__name__}")
        print(f"Payload: {ltp}")
    except Exception as e:
        print(f"❌  get_ltp failed: {e}")

    # ─────────────────────────────────────────────────
    # 3. get_ohlc — OHLC for batch
    # ─────────────────────────────────────────────────
    print_separator("3. get_ohlc() — OHLC for NIFTY, BANKNIFTY")
    try:
        ohlc = groww.get_ohlc(
            exchange_trading_symbols=("NSE:NIFTY", "NSE:BANKNIFTY"),
            segment=groww.SEGMENT_CASH,
        )
        print(f"Type: {type(ohlc).__name__}")
        print(f"Payload: {ohlc}")
    except Exception as e:
        print(f"❌  get_ohlc failed: {e}")

    # ─────────────────────────────────────────────────
    # 4. get_historical_candles — last 2 hours 1-min data
    # ─────────────────────────────────────────────────
    print_separator("4. get_historical_candles() — NIFTY last 2 hours 1min")
    try:
        now = datetime.now()
        two_hours_ago = now - timedelta(hours=2)
        hist = groww.get_historical_candles(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            groww_symbol="NIFTY",
            start_time=two_hours_ago.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            candle_interval="1minute",
        )
        print(f"Type: {type(hist).__name__}")
        if isinstance(hist, dict):
            print(f"Keys: {list(hist.keys())}")
        print(f"Payload (first 500 chars): {str(hist)[:500]}")
    except Exception as e:
        print(f"❌  get_historical_candles failed: {e}")

    # ─────────────────────────────────────────────────
    # 5. get_holdings_for_user — portfolio holdings
    # ─────────────────────────────────────────────────
    print_separator("5. get_holdings_for_user() — Portfolio holdings")
    try:
        holdings = groww.get_holdings_for_user()
        print(f"Type: {type(holdings).__name__}")
        if isinstance(holdings, dict):
            print(f"Keys: {list(holdings.keys())}")
        print(f"Payload: {holdings}")
    except Exception as e:
        print(f"❌  get_holdings_for_user failed: {e}")

    # ─────────────────────────────────────────────────
    # 6. get_positions_for_user — open positions
    # ─────────────────────────────────────────────────
    print_separator("6. get_positions_for_user() — Open positions (CASH)")
    try:
        positions = groww.get_positions_for_user(segment=groww.SEGMENT_CASH)
        print(f"Type: {type(positions).__name__}")
        if isinstance(positions, dict):
            print(f"Keys: {list(positions.keys())}")
        print(f"Payload: {positions}")
    except Exception as e:
        print(f"❌  get_positions_for_user failed: {e}")

    # ─────────────────────────────────────────────────
    # 7. get_available_margin_details — margin info
    # ─────────────────────────────────────────────────
    print_separator("7. get_available_margin_details() — Margin")
    try:
        margin = groww.get_available_margin_details()
        print(f"Type: {type(margin).__name__}")
        if isinstance(margin, dict):
            print(f"Keys: {list(margin.keys())}")
        print(f"Payload: {margin}")
    except Exception as e:
        print(f"❌  get_available_margin_details failed: {e}")

    # ─────────────────────────────────────────────────
    # 8. get_user_profile — account details
    # ─────────────────────────────────────────────────
    print_separator("8. get_user_profile() — Profile")
    try:
        profile = groww.get_user_profile()
        print(f"Type: {type(profile).__name__}")
        if isinstance(profile, dict):
            print(f"Keys: {list(profile.keys())}")
        print(f"Payload: {profile}")
    except Exception as e:
        print(f"❌  get_user_profile failed: {e}")

    print("\n✅  All endpoint tests completed.")


if __name__ == "__main__":
    main()