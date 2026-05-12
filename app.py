import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CBB Dashboard", page_icon="🏀", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] { display: none; }
[data-testid="stSidebarNav"] { display: none; }
[data-testid="collapsedControl"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

st.title("🏀 College Basketball Dashboard")

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
ET         = ZoneInfo("America/New_York")
CBBD_BASE = "https://api.collegebasketballdata.com"

SCORING_EMOJI = {
    "three-point": "🎯",
    "two-point":   "🏀",
    "free throw":  "🔴",
    "dunk":        "💥",
    "layup":       "🤸",
    "tip-in":      "🏀",
}
PLAY_EMOJI = {
    "turnover":  "🚨",
    "steal":     "💨",
    "block":     "🛡️",
    "foul":      "🟡",
    "timeout":   "⏳",
    "rebound":   "🔄",
    "assist":    "🤝",
    "sub":       "🔁",
    "miss":      "❌",
}
MISS_EMOJI = "🤦"

# ──────────────────────────────────────────────────────────────
# API KEY — from Streamlit secrets
# ──────────────────────────────────────────────────────────────
cbbd_key = st.secrets.get("CBBD_API_KEY", "")

def cbbd_headers() -> dict:
    return {"Authorization": f"Bearer {cbbd_key}"}

# ──────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────
_defaults = {
    "selected_game_id":   None,
    "selected_away_name": "",
    "selected_home_name": "",
    "selected_away_abbr": "",
    "selected_home_abbr": "",
    "selected_away_eid":  None,
    "selected_home_eid":  None,
    "selected_year":      None,
    "selected_away_pts":  None,
    "selected_home_pts":  None,
    "cached_events":      None,
    "cached_game_id":      None,
    "filtered_events":    None,
    "filters_applied":    False,
    "last_refresh":       None,
    "search_results":     [],
    "search_done":        False,
    "last_search_year":   None,
    "last_search_team":   None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────
def to_et(raw: str):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ET)
    except Exception:
        return None

def fmt_et(dt) -> str:
    return dt.strftime("%H:%M ET") if dt else "TBD"

def fmt_full_et(dt) -> str:
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S ET")

def team_logo(source_id) -> str:
    return f"https://cdn.collegefootballdata.com/cbb-logos/128/{source_id}.png"

def period_label(p: int) -> str:
    if p == 1: return "H1"
    if p == 2: return "H2"
    return f"OT{p - 2}"

def _emoji(play_type: str, desc: str, is_scoring: bool) -> str:
    pt = (play_type or "").lower()
    d  = (desc or "").lower()
    if any(x in d for x in ["missed", "no good", "miss"]):
        return MISS_EMOJI
    for k, v in SCORING_EMOJI.items():
        if k in pt or k in d:
            return v if is_scoring else "🏀"
    for k, v in PLAY_EMOJI.items():
        if k in pt or k in d:
            return v
    return "🏀"

# ──────────────────────────────────────────────────────────────
# CBBD — FETCH ALL TEAMS (D1 only) + ESPN ID map for logos
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_teams_data() -> tuple:
    try:
        r = requests.get(f"{CBBD_BASE}/teams", headers=cbbd_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            teams    = [t for t in data if t.get("school")]
            names    = sorted([t["school"] for t in teams], key=str.lower)
            logo_map = {t["school"]: str(t["sourceId"]) for t in teams if t.get("sourceId")}
            return names, logo_map
    except Exception:
        pass
    return [], {}

def fetch_all_cbbd_teams() -> list:
    names, _ = fetch_teams_data()
    return names

def fetch_logo_map() -> dict:
    _, logo_map = fetch_teams_data()
    return logo_map

#
