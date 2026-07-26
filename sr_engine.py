"""
SNRZ Strategy engine (Support & Resistance Zindan concept).

Implements, from the PDF:
  S   / R    : raw support / resistance swing points
  SBR        : Support Breakout to Resistance  (support flips to resistance) -> SELL zone
  RBS        : Resistance Breakout to Support  (resistance flips to support) -> BUY zone
  V.S / V.R  : Valid Support / Valid Resistance (a zone price has reacted from cleanly)
  I.VS/I.VR  : Inversion of a valid zone (price came back through it)
  PO2        : Power of (the) Second Touch -- the strongest reaction type, we only
               trust a zone once price has tapped it a 2nd time and reacted
  SRR        : Support Breakout 2 Resistance (two clean rejections confirm it)
  RSS        : Resistance Breakout 2 Support (two clean rejections confirm it)
  GAP        : gap strategy -- an S/R zone left behind by a strong impulsive
               move (a "gap" in the zone map) still respected on return
  False breakout area: a zone wicked through twice but price reclaims it,
               marking it as a trap rather than a real break

Zone confirmation timing rule from the deck: a breakout candle must CLOSE
beyond the zone on the analysis timeframe; a valid target zone needs >= 1
confirmation candle of 5 minutes closing beyond it, full retest confirmation
needs a candle close within 1 hour of the zone.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from . import config


class ZoneType(str, Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"


class ZoneStatus(str, Enum):
    RAW = "raw"                  # single swing point, unconfirmed
    VALID = "valid"              # V.S / V.R -- clean single reaction
    PO2 = "po2"                  # confirmed by a 2nd touch reaction
    FLIPPED = "flipped"          # SBR / RBS -- broken and now the opposite role
    FLIPPED_PO2 = "flipped_po2"  # SRR / RSS -- flipped role confirmed by 2nd reaction
    INVERTED = "inverted"        # I.VS / I.VR -- price came back through a valid zone
    FALSE_BREAK = "false_break"  # wicked through twice, reclaimed -- treat as trap
    GAP = "gap"                  # zone left by an impulsive move (still respected)


@dataclass
class Zone:
    zone_type: ZoneType
    price_high: float
    price_low: float
    status: ZoneStatus
    created_at: object
    touches: int = 0
    label: str = ""

    @property
    def mid(self) -> float:
        return (self.price_high + self.price_low) / 2

    def contains(self, price: float) -> bool:
        return self.price_low <= price <= self.price_high


@dataclass
class Candle:
    time: object
    open: float
    high: float
    low: float
    close: float

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open


def _pip_tolerance(symbol: str) -> float:
    # crude pip-size guess; override per-symbol if needed
    if "JPY" in symbol:
        return config.ZONE_MERGE_TOLERANCE_PIPS * 0.01
    if symbol.upper() in ("XAUUSD", "GOLD"):
        return config.ZONE_MERGE_TOLERANCE_PIPS * 0.1
    return config.ZONE_MERGE_TOLERANCE_PIPS * 0.0001


def find_swing_points(candles: List[Candle], left: int = 2, right: int = 2):
    """Simple fractal swing high/low detector."""
    highs, lows = [], []
    for i in range(left, len(candles) - right):
        window = candles[i - left:i + right + 1]
        c = candles[i]
        if c.high == max(w.high for w in window):
            highs.append(c)
        if c.low == min(w.low for w in window):
            lows.append(c)
    return highs, lows


def build_zones(candles: List[Candle], symbol: str) -> List[Zone]:
    """
    Build raw S/R zones from swing points, then merge nearby ones,
    exactly like drawing horizontal S/R lines on the chart in the deck.
    """
    highs, lows = find_swing_points(candles)
    tol = _pip_tolerance(symbol)
    zones: List[Zone] = []

    for h in highs:
        zones.append(Zone(ZoneType.RESISTANCE, h.high + tol, h.high - tol,
                           ZoneStatus.RAW, h.time, label="R"))
    for l in lows:
        zones.append(Zone(ZoneType.SUPPORT, l.low + tol, l.low - tol,
                           ZoneStatus.RAW, l.time, label="S"))

    # merge overlapping zones of the same type
    zones.sort(key=lambda z: z.mid)
    merged: List[Zone] = []
    for z in zones:
        if merged and merged[-1].zone_type == z.zone_type and \
           abs(merged[-1].mid - z.mid) <= tol * 2:
            merged[-1].price_high = max(merged[-1].price_high, z.price_high)
            merged[-1].price_low = min(merged[-1].price_low, z.price_low)
        else:
            merged.append(z)
    return merged


def _closes_beyond(candle: Candle, zone: Zone) -> Optional[str]:
    """Returns 'up' if candle closes above the zone, 'down' if below, else None."""
    if candle.close > zone.price_high:
        return "up"
    if candle.close < zone.price_low:
        return "down"
    return None


def update_zone_status(zone: Zone, candles_after: List[Candle]) -> Zone:
    """
    Walk forward through candles after the zone was created and evolve its
    status through the SNRZ state machine:
      RAW -> VALID (1 clean reaction, close doesn't break it)
      VALID -> PO2 (2nd touch reacts again without a confirmed close-through)
      VALID -> FLIPPED (SBR/RBS: a candle CLOSES through it)
      FLIPPED -> FLIPPED_PO2 (SRR/RSS: price returns and reacts off the new role)
      VALID -> INVERTED (I.VS/I.VR: price closes back through a valid zone)
      any -> FALSE_BREAK: two closes through in opposite directions within
             FALSE_BREAKOUT_LOOKBACK bars (a trap, not a real break)
    """
    closes_through_directions = []

    for i, c in enumerate(candles_after):
        touched = zone.contains(c.low) or zone.contains(c.high) or zone.contains(c.close)
        direction = _closes_beyond(c, zone)

        if direction:
            closes_through_directions.append(direction)

        if touched and not direction:
            zone.touches += 1
            if zone.status == ZoneStatus.RAW:
                zone.status = ZoneStatus.VALID
            elif zone.status == ZoneStatus.VALID and zone.touches >= config.PO2_MIN_TOUCHES:
                zone.status = ZoneStatus.PO2
            elif zone.status == ZoneStatus.FLIPPED and zone.touches >= config.PO2_MIN_TOUCHES:
                zone.status = ZoneStatus.FLIPPED_PO2

        if direction == "up" and zone.zone_type == ZoneType.RESISTANCE:
            # resistance broken upward and closed -> flips to support (RBS)
            zone.zone_type = ZoneType.SUPPORT
            zone.status = ZoneStatus.FLIPPED
            zone.label = "RBS"
        elif direction == "down" and zone.zone_type == ZoneType.SUPPORT:
            # support broken downward and closed -> flips to resistance (SBR)
            zone.zone_type = ZoneType.RESISTANCE
            zone.status = ZoneStatus.FLIPPED
            zone.label = "SBR"
        elif direction and zone.status == ZoneStatus.VALID:
            # valid zone closed through without a role flip pattern -> inversion
            zone.status = ZoneStatus.INVERTED
            zone.label = "I." + zone.label if not zone.label.startswith("I.") else zone.label

        # false-breakout detection: two opposite-direction closes through the
        # same zone within the lookback window
        if len(closes_through_directions) >= 2:
            recent = closes_through_directions[-2:]
            if recent[0] != recent[1] and i <= config.FALSE_BREAKOUT_LOOKBACK:
                zone.status = ZoneStatus.FALSE_BREAK
                zone.label = "FALSE_BREAKOUT"

    return zone


def classify_gap_zones(zones: List[Zone], candles: List[Candle], impulse_body_multiplier: float = 2.5) -> List[Zone]:
    """
    Flags zones left behind by a strong impulsive ("gap") move -- large-bodied
    candles that skip past a zone without testing it -- per the GAP STRATEGY
    slide (a support/resistance pair left untouched after a fast rally/drop).
    """
    if not candles:
        return zones
    avg_body = sum(abs(c.close - c.open) for c in candles) / len(candles)
    for i in range(1, len(candles)):
        body = abs(candles[i].close - candles[i].open)
        if body > avg_body * impulse_body_multiplier:
            for z in zones:
                left_untested = not any(z.contains(c.close) for c in candles[max(0, i - 5):i])
                spans_zone = min(candles[i].open, candles[i].close) < z.price_low and \
                             max(candles[i].open, candles[i].close) > z.price_high
                if left_untested and not spans_zone and z.status in (ZoneStatus.RAW, ZoneStatus.VALID):
                    z.status = ZoneStatus.GAP
                    z.label = "GAP"
    return zones


# ── Signal classification matching the SNRZ "types of zone determination" ───

def buy_confirmations(zones: List[Zone]) -> List[Zone]:
    """VS, I.VR, RBS, SRR -> bullish confirmations."""
    out = []
    for z in zones:
        if z.zone_type == ZoneType.SUPPORT and z.status == ZoneStatus.VALID:
            out.append(z)   # V.S
        if z.zone_type == ZoneType.SUPPORT and z.status == ZoneStatus.INVERTED and z.label.startswith("I.R"):
            out.append(z)   # I.VR (an inverted resistance now acting as support)
        if z.status == ZoneStatus.FLIPPED and z.label == "RBS":
            out.append(z)
        if z.status == ZoneStatus.FLIPPED_PO2 and z.label == "RBS":
            out.append(z)   # SRR
    return out


def sell_confirmations(zones: List[Zone]) -> List[Zone]:
    """VR, I.VS, SBR, RSS -> bearish confirmations."""
    out = []
    for z in zones:
        if z.zone_type == ZoneType.RESISTANCE and z.status == ZoneStatus.VALID:
            out.append(z)   # V.R
        if z.zone_type == ZoneType.RESISTANCE and z.status == ZoneStatus.INVERTED and z.label.startswith("I.S"):
            out.append(z)   # I.VS
        if z.status == ZoneStatus.FLIPPED and z.label == "SBR":
            out.append(z)
        if z.status == ZoneStatus.FLIPPED_PO2 and z.label == "SBR":
            out.append(z)   # RSS
    return out
