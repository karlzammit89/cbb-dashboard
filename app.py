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
ET        = ZoneInfo("America/New_York")
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
    "cached_game_id":     None,
    "filtered_events":    None,
    "filters_applied":    False,
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
    """
    Returns (team_names_sorted, school_to_source_id_dict).
    CBBD only tracks D1 teams so no division filtering needed.
    sourceId on each team object is the ESPN/CDN numeric ID used in logo URLs.
    """
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

# ──────────────────────────────────────────────────────────────
# CBBD — PLAY-BY-PLAY
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def cbbd_fetch_plays(game_id: int) -> list:
    try:
        r = requests.get(
            f"{CBBD_BASE}/plays/game/{game_id}",
            headers=cbbd_headers(),
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []

def get_events(game_id: int) -> list:
    if st.session_state.cached_game_id == game_id and st.session_state.cached_events is not None:
        return st.session_state.cached_events

    raw    = cbbd_fetch_plays(game_id)
    events = []

    for p in raw:
        period_num = p.get("period", 0)

        desc      = p.get("playText") or p.get("play_text") or ""
        play_type = p.get("playType") or p.get("play_type") or ""

        _clock_raw = p.get("clock") or p.get("clockTime") or ""
        if isinstance(_clock_raw, dict):
            _mins = int(_clock_raw.get("minutes", 0) or 0)
            _secs = int(_clock_raw.get("seconds", 0) or 0)
            clock_val = f"{_mins:02}:{_secs:02}"
        elif isinstance(_clock_raw, str):
            clock_val = _clock_raw
        else:
            clock_val = ""

        # CBBD provides home/away scores directly — no offense/defense mapping needed
        home_sc = int(p.get("homeScore") or p.get("home_score") or 0)
        away_sc = int(p.get("awayScore") or p.get("away_score") or 0)

        # CBBD uses "scoring_play" (not "scoring") per the API spec
        is_scoring = bool(p.get("scoring_play") or p.get("scoringPlay") or p.get("scoring") or False)
        action_dt  = to_et(p.get("wallclock") or p.get("wallClock") or "")

        team = p.get("team") or p.get("offense") or ""

        events.append({
            "period":        period_num,
            "period_label":  period_label(period_num),
            "clock_str":     clock_val,
            "desc":          desc,
            "play_type":     play_type,
            "away_score":    away_sc,
            "home_score":    home_sc,
            "score_str":     f"{away_sc} – {home_sc}",
            "is_scoring":    is_scoring,
            "action_dt":     action_dt,
            "action_dt_str": fmt_full_et(action_dt),
            "team":          team,
            "emoji":         _emoji(play_type, desc, is_scoring),
        })

    # Sort by wallclock, fall back to period + clock countdown
    def _sort_key(e):
        if e["action_dt"]:
            return (0, e["action_dt"].timestamp(), 0, 0)
        try:
            parts = e["clock_str"].split(":")
            secs_remaining = int(parts[0]) * 60 + int(parts[1])
        except Exception:
            secs_remaining = 0
        return (1, 0, e["period"], -secs_remaining)

    events.sort(key=_sort_key)

    st.session_state.cached_events  = events
    st.session_state.cached_game_id = game_id
    return events


# ══════════════════════════════════════════════════════════════
# GAME FEED VIEW
# ══════════════════════════════════════════════════════════════
if st.session_state.selected_game_id:

    game_id   = st.session_state.selected_game_id
    away_name = st.session_state.selected_away_name
    home_name = st.session_state.selected_home_name
    away_eid  = st.session_state.selected_away_eid
    home_eid  = st.session_state.selected_home_eid

    _team = st.session_state.get("last_search_team")
    _year = st.session_state.get("last_search_year")
    if _team:
        col_back1, col_back2, _ = st.columns([1, 2, 5], gap="small")
    else:
        col_back1, _ = st.columns([1, 11], gap="small")
        col_back2 = None
    with col_back1:
        if st.button("⬅ Back"):
            for k in ("cached_events", "cached_game_id", "filtered_events"):
                st.session_state[k] = None
            st.session_state.filters_applied  = False
            st.session_state.selected_game_id = None
            st.session_state.search_results   = []
            st.session_state.search_done      = False
            st.rerun()
    if col_back2 and _team:
        with col_back2:
            if st.button(f"⬅ Back to {_team} {_year}"):
                for k in ("cached_events", "cached_game_id", "filtered_events"):
                    st.session_state[k] = None
                st.session_state.filters_applied  = False
                st.session_state.selected_game_id = None
                st.rerun()

    with st.spinner("Loading play-by-play…"):
        events = get_events(game_id)

    if not events:
        st.warning("No plays returned. The game may not be indexed yet or play-by-play may not be available for this game.")
        st.stop()

    # Use the final score stored at game-select time (sourced directly from search results)
    # This is more reliable than re-querying the API or reading from play-by-play
    _stored_away = st.session_state.get("selected_away_pts")
    _stored_home = st.session_state.get("selected_home_pts")
    if _stored_away is not None and _stored_home is not None:
        live_away, live_home = _stored_away, _stored_home
    else:
        # Fallback: last play scores (may lag by 1 play but better than nothing)
        live_away = events[-1]["away_score"] if events else 0
        live_home = events[-1]["home_score"] if events else 0

    c1, c2, c3 = st.columns([1, 6, 1])
    with c1:
        if away_eid:
            st.image(team_logo(away_eid), width=60)
    with c2:
        st.markdown(
            f"""<div style="display:flex;align-items:center;justify-content:center;
                font-weight:700;font-size:clamp(16px,2.6vw,28px);gap:10px;flex-wrap:wrap;text-align:center;">
                <span>{away_name}</span><span style="color:#888;">{live_away}</span>
                <span>–</span>
                <span style="color:#888;">{live_home}</span><span>{home_name}</span>
            </div>""",
            unsafe_allow_html=True,
        )
    with c3:
        if home_eid:
            st.image(team_logo(home_eid), width=60)

    has_wc = sum(1 for e in events if e["action_dt"])
    total  = len(events)
    pct    = int(100 * has_wc / total) if total else 0
    if pct == 100:
        st.success(f"🕐 Timestamps on all {total} plays")
    elif pct >= 70:
        st.info(f"🕐 Timestamps on {has_wc}/{total} plays ({pct}%)")
    else:
        st.warning(f"🕐 Timestamps sparse: {has_wc}/{total} plays ({pct}%) — time filter may return few results")

    st.divider()

    all_dts      = [e["action_dt"] for e in events if e["action_dt"]]
    gs_default   = min(all_dts) if all_dts else None
    ge_default   = max(all_dts) if all_dts else None
    def _period_sort_key(label: str) -> int:
        if label == "H1":  return 1
        if label == "H2":  return 2
        try: return 2 + int(label[2:])  # OT1->3, OT2->4 ...
        except Exception: return 99
    all_periods = sorted({e["period_label"] for e in events}, key=_period_sort_key)
    all_teams = sorted({e["team"] for e in events if e["team"]})

    USE_Q  = st.checkbox("🏀 Filter by Half / OT")
    USE_T  = st.checkbox("🕐 Filter by Actual Time (ET)")
    USE_TM = st.checkbox("🏟️ Filter by Team")
    USE_SC = st.checkbox("🔥 Scoring Plays Only")

    sel_halves = sel_teams = []
    START_DT = END_DT = None

    if USE_Q:
        sel_halves = st.multiselect("Half / OT", options=all_periods)
    if USE_T:
        if not all_dts:
            st.warning("No wall-clock timestamps available.")
        else:
            tc1, tc2 = st.columns(2)
            with tc1:
                sd  = st.date_input("Start date", gs_default.date(), key="sd")
                st_ = st.time_input("Start time", gs_default.time(), step=60, key="st_")
            with tc2:
                ed  = st.date_input("End date",   ge_default.date(), key="ed")
                et_ = st.time_input("End time",   ge_default.time(), step=60, key="et_")
            START_DT = datetime.combine(sd, st_).replace(tzinfo=ET)
            END_DT   = datetime.combine(ed, et_).replace(tzinfo=ET)
    if USE_TM:
        sel_teams = st.multiselect("Team", options=all_teams)

    if st.button("🚀 Apply Filters"):
        def passes(e):
            if USE_Q  and sel_halves and e["period_label"] not in sel_halves: return False
            if USE_T  and START_DT and END_DT:
                if not e["action_dt"] or not (START_DT <= e["action_dt"] <= END_DT): return False
            if USE_SC and not e["is_scoring"]:                                        return False
            if USE_TM and sel_teams and e["team"] not in sel_teams:                   return False
            return True
        st.session_state.filtered_events = [e for e in events if passes(e)]
        st.session_state.filters_applied = True

    fa       = st.session_state.filters_applied
    filtered = st.session_state.filtered_events if fa else events

    if fa:
        n, t = len(filtered), len(events)
        if n == 0:
            st.warning("⚠️ No plays match — adjust filters and click Apply again.")
            st.stop()
        if USE_Q:
            st.info(f"🏀 Half filter: {', '.join(sel_halves or ['none'])} — showing {n} of {t} plays")
        if USE_T and START_DT and END_DT:
            st.info(f"🕐 Time filter: {START_DT.strftime('%Y-%m-%d %H:%M ET')} → {END_DT.strftime('%Y-%m-%d %H:%M ET')} — showing {n} of {t} plays")
        if USE_TM:
            st.info(f"🏟️ Team filter: {', '.join(sel_teams or ['none'])} — showing {n} of {t} plays")
        if USE_SC:
            st.info(f"🔥 Scoring plays filter — showing {n} of {t} plays")

    for e in filtered:
        st.subheader(f"{e['emoji']} {e['period_label']} | ⏱️ {e['clock_str']}")
        meta_parts = []
        if e["play_type"]: meta_parts.append(f"**{e['play_type']}**")
        if e["team"]:      meta_parts.append(f"{e['team']}")
        if meta_parts:     st.caption("  ·  ".join(meta_parts))
        score_line = f"📊 **Score:** {e['score_str']}"
        if e["is_scoring"]:
            score_line += " &nbsp; 🔥 *Scoring Play!*"
        st.markdown(score_line)
        st.markdown(f"📋 **Play:** {e['desc']}")
        st.markdown(f"🕐 **Time (ET):** `{e['action_dt_str']}`")
        st.divider()


# ══════════════════════════════════════════════════════════════
# HOME — SEARCH GAMES
# ══════════════════════════════════════════════════════════════
else:
    st.markdown("Search by team name to find a game, then click to load its play-by-play.")

    all_teams = fetch_all_cbbd_teams()

    default_season = st.session_state.last_search_year or datetime.today().year

    col_a, col_b = st.columns([3, 1])
    with col_a:
        if all_teams:
            search_team = st.selectbox(
                "Team",
                options=[""] + all_teams,
                format_func=lambda x: "Select a team..." if x == "" else x,
                label_visibility="collapsed",
            )
        else:
            search_team = st.text_input(
                "Team name",
                placeholder="e.g. Duke, Kentucky, Kansas",
                label_visibility="collapsed",
            )
    with col_b:
        search_year = st.number_input(
            "Season",
            min_value=2010,
            max_value=2030,
            value=default_season,
            step=1,
            label_visibility="collapsed",
            help="Use the year the season ends — e.g. 2025 = 2024-25 season",
        )

    if st.button("🔎 Find Games", use_container_width=True):
        if not cbbd_key:
            st.error("No CBBD API key found. Add CBBD_API_KEY to your Streamlit secrets.")
        elif not search_team.strip():
            st.warning("Select a team first.")
        else:
            st.session_state.last_search_year = int(search_year)
            st.session_state.last_search_team = search_team.strip()
            with st.spinner(f"Searching CBBD for {search_team}…"):
                try:
                    r = requests.get(
                        f"{CBBD_BASE}/games",
                        headers=cbbd_headers(),
                        params={"season": int(search_year), "team": search_team.strip()},
                        timeout=10,
                    )
                    r.raise_for_status()
                    found = r.json()
                    st.session_state.search_results = found if isinstance(found, list) else []
                    st.session_state.search_done    = True
                    if not st.session_state.search_results:
                        st.warning("No games found — try a different team or season year.")
                except Exception as e:
                    st.error(f"Search failed: {e}")

    if st.session_state.search_done and st.session_state.search_results:
        logo_map = fetch_logo_map()
        results = sorted(
            st.session_state.search_results,
            key=lambda x: x.get("startDate", x.get("start_date", "")),
            reverse=True,
        )
        st.markdown(f"**{len(results)} game(s) found:**")

        for g in results:
            _raw_dt = g.get("startDate") or g.get("start_date") or ""
            try:
                _et_dt = datetime.fromisoformat(_raw_dt.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
                g_date = _et_dt.strftime("%Y-%m-%d")
            except Exception:
                g_date = _raw_dt[:10]

            g_away     = g.get("awayTeam")   or g.get("away_team")   or "?"
            g_home     = g.get("homeTeam")   or g.get("home_team")   or "?"
            g_away_pts = g.get("awayPoints") or g.get("away_points") or ""
            g_home_pts = g.get("homePoints") or g.get("home_points") or ""
            g_id       = g.get("id")

            # Resolve ESPN IDs by team name for logo URLs
            g_away_sid = logo_map.get(g_away, "")
            g_home_sid = logo_map.get(g_home, "")

            g_stype = (g.get("seasonType") or g.get("season_type") or "regular").lower()
            if "post" in g_stype or "tournament" in g_stype:
                week_label = "Postseason / Tournament"
            else:
                week_label = "Regular Season"

            with st.container(border=True):
                away_pts_str = str(g_away_pts) if g_away_pts != "" else ""
                home_pts_str = str(g_home_pts) if g_home_pts != "" else ""

                _a_logo  = f"<img src='{team_logo(g_away_sid)}' style='width:22px;height:22px;object-fit:contain'/>" if g_away_sid else "<span style='width:22px;display:inline-block'></span>"
                _h_logo  = f"<img src='{team_logo(g_home_sid)}' style='width:22px;height:22px;object-fit:contain'/>" if g_home_sid else "<span style='width:22px;display:inline-block'></span>"
                _a_score = f"<span style='margin-left:auto;font-size:15px;font-weight:700;color:#aaa'>{away_pts_str}</span>" if away_pts_str else ""
                _h_score = f"<span style='margin-left:auto;font-size:15px;font-weight:700;color:#aaa'>{home_pts_str}</span>" if home_pts_str else ""

                card_html = (
                    f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:3px'>{_a_logo}"
                    f"<span style='font-size:15px;font-weight:700'>{g_away}</span>{_a_score}</div>"
                    f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>{_h_logo}"
                    f"<span style='font-size:15px;font-weight:700'>{g_home}</span>{_h_score}</div>"
                    f"<div style='font-size:12px;color:#888;border-top:1px solid rgba(255,255,255,0.07);padding-top:4px'>"
                    f"{g_date} &middot; {week_label}</div>"
                )
                st.markdown(card_html, unsafe_allow_html=True)

                if st.button("▶ Open", key=f"pick_{g_id}", use_container_width=True):
                    for k in ("cached_events", "cached_game_id", "filtered_events"):
                        st.session_state[k] = None
                    st.session_state.filters_applied    = False
                    st.session_state.selected_game_id   = g_id
                    st.session_state.selected_away_name = g_away
                    st.session_state.selected_home_name = g_home
                    st.session_state.selected_away_abbr = g_away[:6].upper()
                    st.session_state.selected_home_abbr = g_home[:6].upper()
                    st.session_state.selected_away_eid  = g_away_sid
                    st.session_state.selected_home_eid  = g_home_sid
                    st.session_state.selected_away_pts  = int(g_away_pts) if str(g_away_pts).isdigit() else None
                    st.session_state.selected_home_pts  = int(g_home_pts) if str(g_home_pts).isdigit() else None
                    st.session_state.selected_year      = int(g.get("season") or search_year)
                    # Keep search_results and search_done so Back to team schedule restores the list
                    st.rerun()
