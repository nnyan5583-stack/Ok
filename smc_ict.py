"""
SMC / ICT confluence layer.

This supplies the confirmation the SNRZ deck references directly
(e.g. "FVG-OB-RC" mentioned on the NOP slide, "Liquidity Sweep & Liquidity
Run" on its own SNRZ slide) plus the standard ICT toolkit used to validate
an SNRZ zone before an order is placed:

  Liquidity Sweep : price wicks through equal highs/lows (resting liquidity)
                     and reverses -- the deck's own definition: "an area
                     where price has done the same thing twice, marking
                     liquidity that will be swept and later respected".
  Liquidity Run    : a decisive break through a liquidity pool that keeps
                      running instead of reversing (continuation, not a trap).
  FVG              : Fair Value Gap / imbalance -- a 3-candle gap where the
                      wick of candle 1 and candle 3 don't overlap.
  Order Block      : the last opposite-colored candle before a BOS impulse.
  BOS / CHoCH       : Break of Structure / Change of Character, used to
                      confirm the trend direction feeding the SNRZ zone.
"""

from dataclasses import dataclass
from typing import List, Optional

from . import config
from .sr_engine import Candle


@dataclass
class Liquidity:
    kind: str          # "sweep" or "run"
    direction: str      # "bullish" or "bearish"
    level: float
    time: object


@dataclass
class FVG:
    direction: str       # "bullish" or "bearish"
    top: float
    bottom: float
    time: object

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class OrderBlock:
    direction: str        # "bullish" or "bearish"
    high: float
    low: float
    time: object

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


def detect_equal_levels(candles: List[Candle], tolerance: float, lookback: int):
    window = candles[-lookback:]
    equal_highs, equal_lows = [], []
    for i in range(len(window)):
        for j in range(i + 1, len(window)):
            if abs(window[i].high - window[j].high) <= tolerance:
                equal_highs.append((window[i], window[j]))
            if abs(window[i].low - window[j].low) <= tolerance:
                equal_lows.append((window[i], window[j]))
    return equal_highs, equal_lows


def detect_liquidity_events(candles: List[Candle], tolerance: float) -> List[Liquidity]:
    """
    Marks a Liquidity Sweep when price wicks beyond an equal-high/low pool
    and closes back inside (a trap / reversal signal), and a Liquidity Run
    when a later candle closes firmly beyond the pool (continuation).
    """
    events: List[Liquidity] = []
    equal_highs, equal_lows = detect_equal_levels(candles, tolerance, config.LIQUIDITY_SWEEP_LOOKBACK)

    for a, b in equal_highs:
        pool = max(a.high, b.high)
        for c in candles[candles.index(b) + 1:]:
            if c.high > pool and c.close < pool:
                events.append(Liquidity("sweep", "bearish", pool, c.time))
                break
            if c.close > pool:
                events.append(Liquidity("run", "bullish", pool, c.time))
                break

    for a, b in equal_lows:
        pool = min(a.low, b.low)
        for c in candles[candles.index(b) + 1:]:
            if c.low < pool and c.close > pool:
                events.append(Liquidity("sweep", "bullish", pool, c.time))
                break
            if c.close < pool:
                events.append(Liquidity("run", "bearish", pool, c.time))
                break

    return events


def detect_fvgs(candles: List[Candle], min_gap: float) -> List[FVG]:
    fvgs = []
    for i in range(2, len(candles)):
        c1, c2, c3 = candles[i - 2], candles[i - 1], candles[i]
        # bullish FVG: candle1 high < candle3 low
        if c3.low - c1.high >= min_gap:
            fvgs.append(FVG("bullish", top=c3.low, bottom=c1.high, time=c2.time))
        # bearish FVG: candle1 low > candle3 high
        if c1.low - c3.high >= min_gap:
            fvgs.append(FVG("bearish", top=c1.low, bottom=c3.high, time=c2.time))
    return fvgs


def detect_order_blocks(candles: List[Candle], lookback: int) -> List[OrderBlock]:
    """Last opposite candle before a strong impulsive move (BOS)."""
    blocks = []
    avg_range = sum(c.high - c.low for c in candles) / max(len(candles), 1)
    for i in range(lookback, len(candles)):
        impulse = candles[i]
        impulse_size = impulse.high - impulse.low
        if impulse_size < avg_range * 1.8:
            continue
        # walk back to find the last opposite-colored candle
        for j in range(i - 1, max(i - lookback, 0), -1):
            prev = candles[j]
            if impulse.bullish and prev.bearish:
                blocks.append(OrderBlock("bullish", prev.high, prev.low, prev.time))
                break
            if impulse.bearish and prev.bullish:
                blocks.append(OrderBlock("bearish", prev.high, prev.low, prev.time))
                break
    return blocks


def detect_bos(candles: List[Candle], swing_highs, swing_lows) -> Optional[str]:
    """
    Very simple BOS/CHoCH check: does the latest close break the most
    recent confirmed swing high (bullish BOS) or swing low (bearish BOS)?
    """
    if not candles:
        return None
    last = candles[-1]
    if swing_highs and last.close > swing_highs[-1].high:
        return "bullish_bos"
    if swing_lows and last.close < swing_lows[-1].low:
        return "bearish_bos"
    return None


def smc_confluence(direction: str, price: float, fvgs: List[FVG],
                    order_blocks: List[OrderBlock], liquidity_events: List[Liquidity]) -> bool:
    """
    True if there's SMC confluence supporting `direction` ("buy"/"sell") at
    the current price -- i.e. price sits inside a same-direction FVG or
    order block, AND a liquidity sweep in the same direction has occurred
    recently. This is the confirmation gate the SNRZ deck implies by
    referencing FVG-OB-RC alongside NOP.
    """
    want = "bullish" if direction == "buy" else "bearish"

    in_fvg = any(f.direction == want and f.contains(price) for f in fvgs)
    in_ob = any(o.direction == want and o.contains(price) for o in order_blocks)
    swept = any(e.kind == "sweep" and e.direction == want for e in liquidity_events)

    if not config.REQUIRE_SMC_CONFLUENCE:
        return True
    return (in_fvg or in_ob) and swept
