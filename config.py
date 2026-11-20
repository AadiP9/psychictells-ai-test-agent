"""
config.py
─────────────────────────────────────────────────────────────────────────────
Central configuration — now profile-driven for multi-site reusability.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import math as _math
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_agent.site_profile import SiteProfile, SiteProfileError

# ── Load the active site profile ────────────────────────────────────────────
try:
    _profile = SiteProfile.load()
except SiteProfileError as e:
    print(f"\n❌  CONFIG ERROR: {e}\n")
    raise SystemExit(1)

SITE_NAME    = _profile.site_name
SITE_DISPLAY = _profile.display_name
SITE_DOMAIN  = _profile.domain
EXPERT_DOMAIN = _profile.expert_domain

# ── Site URLs ────────────────────────────────────────────────────────────────
BASE_URL         = _profile.base_url
PSYCHICS_URL     = _profile.listing_url
LOGIN_URL        = _profile.login_url
SIGNUP_URL       = _profile.signup_url
ACCOUNT_URL      = _profile.account_url

EXPERT_BASE      = _profile.expert_base
EXPERT_LOGIN_URL = _profile.expert_login_url
EXPERT_DASHBOARD = _profile.expert_dashboard

# ── Credentials ──────────────────────────────────────────────────────────────
_creds = _profile.credentials
USER_EMAIL    = os.getenv(_creds.get("user_email_env", "USER_EMAIL"),
                           _creds.get("user_email_default", ""))
USER_PASSWORD = os.getenv(_creds.get("user_password_env", "USER_PASSWORD"),
                           _creds.get("user_password_default", ""))
USER_NAME     = os.getenv(_creds.get("user_name_env", "USER_NAME"),
                           _creds.get("user_name_default", ""))

EXPERT_EMAIL    = os.getenv(_creds.get("expert_email_env", "EXPERT_EMAIL"),
                             _creds.get("expert_email_default", ""))
EXPERT_PASSWORD = os.getenv(_creds.get("expert_password_env", "EXPERT_PASSWORD"),
                             _creds.get("expert_password_default", ""))

# ── Browser settings ──────────────────────────────────────────────────────────
# FIX: Added default "true" to HEADLESS so missing env var doesn't crash
#      with AttributeError: 'NoneType' has no attribute 'lower'
HEADLESS  = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO   = int(os.getenv("SLOW_MO", "60"))
TIMEOUT   = int(os.getenv("TIMEOUT", "15000"))  # Warmup handles cold starts; 15s is right for element waits
VIEWPORT  = {"width": 1280, "height": 800}

# ── Reporting ─────────────────────────────────────────────────────────────────
REPORTS_DIR     = "reports"
SCREENSHOTS_DIR = "screenshots"
RUN_ID          = datetime.now().strftime("%Y%m%d_%H%M%S")
REPORT_DIR      = f"reports/{RUN_ID}"
HTML_REPORT     = f"{REPORT_DIR}/report.html"
REPORT_FILE     = f"{REPORT_DIR}/report.json"
os.makedirs(REPORT_DIR,      exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# ── AI / Gemini ───────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AI_MODEL       = os.getenv("AI_MODEL", "gemini-3.6-flash")
AI_MODEL_FALLBACKS = os.getenv(
    "AI_MODEL_FALLBACKS",
    "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-flash-latest",
)

def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]

AI_MODELS = list(dict.fromkeys([AI_MODEL, *_split_csv(AI_MODEL_FALLBACKS)]))

# ── Selectors ─────────────────────────────────────────────────────────────────
SELECTORS = _profile.selectors

# ── Site-navigation rules ─────────────────────────────────────────────────────
NON_PROFILE_PATH_SEGMENTS = _profile.non_profile_path_segments
PROFILE_URL_PREFIXES      = _profile.profile_url_prefixes

# ── UI-regression baseline pages ──────────────────────────────────────────────
BASELINE_PAGES = _profile.baseline_pages

# ── Click position profiles ───────────────────────────────────────────────────
def _inset(w, h):
    return max(int(_math.ceil(h / 2)), 8)

CLICK_POSITIONS = [
    ("Center",       lambda w, h: {"x": int(w // 2),           "y": int(h // 2)}),
    ("Top-Left",     lambda w, h: {"x": _inset(w, h),          "y": _inset(w, h)}),
    ("Top-Right",    lambda w, h: {"x": int(w) - _inset(w, h), "y": _inset(w, h)}),
    ("Bottom-Left",  lambda w, h: {"x": _inset(w, h),          "y": int(h) - _inset(w, h)}),
    ("Bottom-Right", lambda w, h: {"x": int(w) - _inset(w, h), "y": int(h) - _inset(w, h)}),
]