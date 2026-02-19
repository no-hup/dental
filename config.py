"""Configuration loader for Dental Voice AI Agent."""

import os
from dotenv import load_dotenv

load_dotenv()

# SignalWire
SIGNALWIRE_PROJECT_ID = os.getenv("SIGNALWIRE_PROJECT_ID", "")
SIGNALWIRE_TOKEN = os.getenv("SIGNALWIRE_TOKEN", "")
SIGNALWIRE_SPACE = os.getenv("SIGNALWIRE_SPACE", "")
SIGNALWIRE_PHONE_NUMBER = os.getenv("SIGNALWIRE_PHONE_NUMBER", "")
DISPLAY_PHONE_NUMBER = os.getenv("DISPLAY_PHONE_NUMBER", "")
SWML_BASIC_AUTH_USER = os.getenv("SWML_BASIC_AUTH_USER", "")
SWML_BASIC_AUTH_PASSWORD = os.getenv("SWML_BASIC_AUTH_PASSWORD", "")
SWML_PROXY_URL_BASE = os.getenv("SWML_PROXY_URL_BASE", "")

# OpenDental API
OPENDENTAL_BASE_URL = os.getenv("OPENDENTAL_BASE_URL", "https://api.opendental.com/api/v1")
OPENDENTAL_DEVELOPER_KEY = os.getenv("OPENDENTAL_DEVELOPER_KEY", "")
OPENDENTAL_CUSTOMER_KEY = os.getenv("OPENDENTAL_CUSTOMER_KEY", "")

# Practice Info
PRACTICE_NAME = os.getenv("PRACTICE_NAME", "our dental office")

# AI Model
AI_MODEL = os.getenv("AI_MODEL", "gpt-oss-120b")
AI_TOP_P = float(os.getenv("AI_TOP_P", "0.5"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.5"))

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "3000"))

# Mock mode
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes")

# Outbound Confirmation Agent
OUTBOUND_ENABLED = os.getenv("OUTBOUND_ENABLED", "false").lower() in ("true", "1", "yes")
OUTBOUND_SCHEDULE = os.getenv("OUTBOUND_SCHEDULE", "0 9 * * 1-5")
CONFIRM_WINDOW_DAYS = int(os.getenv("CONFIRM_WINDOW_DAYS", "3"))
RECALL_WINDOW_DAYS = int(os.getenv("RECALL_WINDOW_DAYS", "14"))
MAX_OUTBOUND_CONCURRENT = int(os.getenv("MAX_OUTBOUND_CONCURRENT", "2"))
OUTBOUND_CALLER_ID = os.getenv("OUTBOUND_CALLER_ID", "") or SIGNALWIRE_PHONE_NUMBER


def validate():
    """Validate required configuration is present."""
    if MOCK_MODE:
        print("*** MOCK MODE enabled — using local SQLite instead of OpenDental API ***")
        return

    missing = []
    if not OPENDENTAL_DEVELOPER_KEY:
        missing.append("OPENDENTAL_DEVELOPER_KEY")
    if not OPENDENTAL_CUSTOMER_KEY:
        missing.append("OPENDENTAL_CUSTOMER_KEY")
    if not SIGNALWIRE_PHONE_NUMBER:
        missing.append("SIGNALWIRE_PHONE_NUMBER")
    if missing:
        print(f"WARNING: Missing config: {', '.join(missing)}")
        print("Some features may not work. Copy .env.example to .env and fill in values.")
