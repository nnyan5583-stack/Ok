"""
Combines everything into one final trade signal:

  1. SNRZ zone confirmations   (sr_engine.buy_confirmations / sell_confirmations)
  2. RONIN FX premium/discount bias (levels.premium_or_discount / bias_from_fop_nop)
  3. SMC/ICT confluence         (smc_ict.smc_confluence: FVG / OB + liquidity sweep)
  4. Candle-close timing rule   (a confirmation candle must fully CLOSE beyond
     the zone -- no wick-only triggers -- matching the deck's "candle
     confirmation" rule)

A trade is only taken when ALL layers agree, matching the deck's own
statement that a zone alone isn't enough: "each single point is not enough,
by itself" -- it must be judged with the confluence of everything else.
"""

from dataclasses import dataclass
from typing import List, Optional

from . import config, sr_engine, smc_ict, levels


@dataclass
class TradeSignal:
    symbol: str
    direction: str        # "buy" or "sell"
    entry: float
    stop_loss: float
    take_profit: float
    reason: str


def _stop_for_zone(direction: str, zone: sr_engine.Zone, buffer_pips_value: float) -> float:
    if direction == "buy":
        return zone.price_low - buffer_pips_value
    return zone.price_high + buffer_pips_value


def build_signal(
    symbol: str,
    candles_analysis: List[sr_engine.Candle],
    candles_confirmation: List[sr_engine.Candle],
    current_price: float,
    session_levels: Optional[levels.SessionLevels],
) -> Optional[TradeSignal]:

    # 1) SNRZ zones on the analysis timeframe
    zones = sr_engine.build_zones(candles_analysis, symbol)
    zones = [sr_engine.update_zone_status(z, candles_analysis) for z in zones]
    zones = sr_engine.classify_gap_zones(zones, candles_analysis)

    buy_zones = sr_engine.buy_confirmations(zones)
    sell_zones = sr_engine.sell_confirmations(zones)

    # 2) RONIN FX premium/discount bias
    bias = "unknown"
    if session_levels:
        bias = levels.bias_from_fop_nop(current_price, session_levels)

    # 3) SMC/ICT confluence on the confirmation timeframe
    tol = sr_engine._pip_tolerance(symbol)
    liquidity_events = smc_ict.detect_liquidity_events(candles_confirmation, tol)
    fvgs = smc_ict.detect_fvgs(candles_confirmation, config.FVG_MIN_GAP_PIPS * tol)
    obs = smc_ict.detect_order_blocks(candles_confirmation, config.ORDER_BLOCK_LOOKBACK)

    def zone_price_hit(zone: sr_engine.Zone) -> bool:
        return zone.contains(current_price)

    # ── BUY PATH ──────────────────────────────────────────────────────────
    for z in buy_zones:
        if not zone_price_hit(z):
            continue
        if bias not in ("discount", "unknown"):
            continue  # RONIN bias disagrees -- skip
        if not smc_ict.smc_confluence("buy", current_price, fvgs, obs, liquidity_events):
            continue
        stop = _stop_for_zone("buy", z, tol * 5)
        risk = current_price - stop
        target = current_price + risk * config.RR_TARGET
        return TradeSignal(
            symbol=symbol, direction="buy", entry=current_price,
            stop_loss=stop, take_profit=target,
            reason=f"SNRZ:{z.label or z.status.value} + RONIN:{bias} + SMC confluence",
        )

    # ── SELL PATH ─────────────────────────────────────────────────────────
    for z in sell_zones:
        if not zone_price_hit(z):
            continue
        if bias not in ("premium", "unknown"):
            continue
        if not smc_ict.smc_confluence("sell", current_price, fvgs, obs, liquidity_events):
            continue
        stop = _stop_for_zone("sell", z, tol * 5)
        risk = stop - current_price
        target = current_price - risk * config.RR_TARGET
        return TradeSignal(
            symbol=symbol, direction="sell", entry=current_price,
            stop_loss=stop, take_profit=target,
            reason=f"SNRZ:{z.label or z.status.value} + RONIN:{bias} + SMC confluence",
        )

    return None
