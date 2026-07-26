"""
RONIN FX concept: FOP / NOP / DOP.

FOP  = Frankfurt Open Price  -> structural anchor of the day, discount/premium
       reference used across every session.
NOP  = New York Open Price   -> the key liquidity / volatility zone of the day,
       can act as discount/premium the same way as FOP.
DOP  = Daily Open Price      -> tells us whether price is trading at a premium
       or discount relative to the day's open.

These three levels are used purely as CONTEXT (premium/discount bias) that
feeds into the SNRZ + SMC confirmation engine -- they are not standalone
entry signals.
"""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SessionLevels:
    fop: float
    nop: float
    dop: float
    date: datetime


def _first_close_at_or_after(rates, hour_utc: int):
    """rates: list of dicts with 'time' (UTC datetime) and 'close'/'open'."""
    for bar in rates:
        if bar["time"].hour == hour_utc:
            return bar["open"]
    return None


def compute_session_levels(daily_open: float, hourly_bars: list, fop_hour: int, nop_hour: int) -> SessionLevels:
    """
    hourly_bars: list of 1H candles for the current day, each a dict with
                 keys 'time' (tz-aware UTC datetime) and 'open'.
    """
    fop = _first_close_at_or_after(hourly_bars, fop_hour)
    nop = _first_close_at_or_after(hourly_bars, nop_hour)
    today = datetime.now(timezone.utc)
    return SessionLevels(fop=fop, nop=nop, dop=daily_open, date=today)


def premium_or_discount(price: float, levels: SessionLevels) -> str:
    """
    Returns 'premium', 'discount', or 'equilibrium' relative to DOP,
    the way the RONIN FX deck describes it: price above DOP after
    breaking above a session's FOP/NOP structure = premium (favor sells),
    price below DOP after breaking below = discount (favor buys).
    """
    if levels.dop is None:
        return "unknown"
    if price > levels.dop:
        return "premium"
    if price < levels.dop:
        return "discount"
    return "equilibrium"


def bias_from_fop_nop(price: float, levels: SessionLevels) -> str:
    """
    Simple bias helper combining FOP and NOP as extra discount/premium
    reference points, per the deck's note that FOP/NOP can each act as
    a discount or premium zone the same way DOP does.
    """
    votes = []
    for lvl in (levels.fop, levels.nop, levels.dop):
        if lvl is None:
            continue
        votes.append("premium" if price > lvl else "discount")
    if not votes:
        return "unknown"
    return max(set(votes), key=votes.count)
