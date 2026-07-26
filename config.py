"""
Configuration for the SNRZ + RONIN FX + SMC/ICT hybrid bot.
Edit these values to match your broker / account / preferences.
"""

import os

# ── MT5 BRIDGE CONNECTION (mt5linux running in the mt5 Docker service) ─────
MT5_BRIDGE_HOST = os.getenv("MT5_BRIDGE_HOST", "mt5.railway.internal")
MT5_BRIDGE_PORT = int(os.getenv("MT5_BRIDGE_PORT", "8001"))

# ── SYMBOLS TO TRADE ────────────────────────────────────────────────────────
SYMBOLS = os.getenv("SYMBOLS", "XAUUSD").split(",")

# ── TIMEFRAMES (SNRZ multi-timeframe waterfall) ─────────────────────────────
# Each entry: (analysis_tf, skip_tf, confirmation_tf)
TIMEFRAME_CHAIN = [
    ("WEEKLY", "DAILY", "4H"),
    ("DAILY",  "4H",    "1H"),
    ("4H",     "1H",    "30M"),
    ("1H",     "30M",   "15M"),
    ("15M",    "5M",    "5M"),
]

# Default working chain used by the live loop (analysis -> confirmation)
ANALYSIS_TF = os.getenv("ANALYSIS_TF", "1H")
CONFIRMATION_TF = os.getenv("CONFIRMATION_TF", "5M")

# ── SESSION OPEN PRICES (RONIN FX: FOP / NOP / DOP) ─────────────────────────
# Times below are in UTC. Kurdistan (Asia/Baghdad, UTC+3) local times from the
# PDF: FOP ≈ 09:00 local (06:00 UTC), NOP ≈ 15:30/16:30 local (12:30/13:30 UTC
# winter/summer). Adjust FOP_UTC_HOUR / NOP_UTC_HOUR if your broker server
# time differs.
FOP_UTC_HOUR = int(os.getenv("FOP_UTC_HOUR", "6"))    # Frankfurt open
NOP_UTC_HOUR = int(os.getenv("NOP_UTC_HOUR", "13"))   # New York open (DST-aware, adjust seasonally)

# ── SNRZ ZONE / TOUCH RULES ──────────────────────────────────────────────────
PO2_MIN_TOUCHES = 2              # Power of Second Touch = 2nd reaction off the zone
FALSE_BREAKOUT_LOOKBACK = 30     # bars to look back for a false-breakout zone
ZONE_MERGE_TOLERANCE_PIPS = 15   # merge S/R lines closer than this into one zone

# ── SMC / ICT SETTINGS ───────────────────────────────────────────────────────
LIQUIDITY_SWEEP_LOOKBACK = 50    # bars scanned for equal highs/lows (liquidity pools)
FVG_MIN_GAP_PIPS = 3             # minimum imbalance size to count as a valid FVG
ORDER_BLOCK_LOOKBACK = 20        # bars scanned back from a BOS to find the OB candle

# ── CONFIRMATION REQUIREMENTS (per SNRZ master class slide) ─────────────────
# BUY needs one of:  VS, I.VR, RBS, SRR   (+ SMC confluence below)
# SELL needs one of: VR, I.VS, SBR, RSS   (+ SMC confluence below)
REQUIRE_SMC_CONFLUENCE = True    # also require liquidity sweep + FVG/OB in same direction
MIN_CANDLE_CONFIRMATION_MINUTES = 5   # a candle must fully close beyond the zone (no wick-only)

# ── RISK MANAGEMENT ─────────────────────────────────────────────────────────
RISK_PERCENT_PER_TRADE = float(os.getenv("RISK_PERCENT", "1.0"))   # % of balance risked per trade
RR_TARGET = float(os.getenv("RR_TARGET", "2.0"))                    # reward:risk ratio for TP
MAX_OPEN_TRADES_PER_SYMBOL = 1
MAGIC_NUMBER = 990211

# ── LOOP TIMING ──────────────────────────────────────────────────────────────
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))
