"""
MT5 execution layer. Talks to the MT5 terminal running in the separate
`mt5` Railway service (Wine + mt5linux bridge on port 8001), NOT to MT5
directly -- this process runs on plain Linux.

Requires: pip install pymt5linux
"""

import time
from datetime import datetime, timezone
from typing import List, Optional

from . import config
from .sr_engine import Candle

_TF_MAP = {
    "1M": None, "5M": None, "15M": None, "30M": None,
    "1H": None, "4H": None, "DAILY": None, "WEEKLY": None,
}


class MT5Client:
    def __init__(self):
        from pymt5linux import MetaTrader5  # imported lazily so the module
        self.mt5 = MetaTrader5(host=config.MT5_BRIDGE_HOST, port=config.MT5_BRIDGE_PORT)
        ok = self.mt5.initialize()
        if not ok:
            raise RuntimeError(f"MT5 initialize() failed: {self.mt5.last_error()}")

        # resolve timeframe constants now that self.mt5 exists
        self.tf_map = {
            "1M": self.mt5.TIMEFRAME_M1,
            "5M": self.mt5.TIMEFRAME_M5,
            "15M": self.mt5.TIMEFRAME_M15,
            "30M": self.mt5.TIMEFRAME_M30,
            "1H": self.mt5.TIMEFRAME_H1,
            "4H": self.mt5.TIMEFRAME_H4,
            "DAILY": self.mt5.TIMEFRAME_D1,
            "WEEKLY": self.mt5.TIMEFRAME_W1,
        }

    def get_candles(self, symbol: str, timeframe: str, count: int = 300) -> List[Candle]:
        tf = self.tf_map[timeframe]
        rates = self.mt5.copy_rates_from_pos(symbol, tf, 0, count)
        candles = []
        for r in rates:
            candles.append(Candle(
                time=datetime.fromtimestamp(r["time"], tz=timezone.utc),
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
            ))
        return candles

    def get_hourly_bars_today(self, symbol: str) -> List[dict]:
        candles = self.get_candles(symbol, "1H", count=48)
        today = datetime.now(timezone.utc).date()
        return [{"time": c.time, "open": c.open} for c in candles if c.time.date() == today]

    def get_daily_open(self, symbol: str) -> Optional[float]:
        candles = self.get_candles(symbol, "DAILY", count=2)
        return candles[-1].open if candles else None

    def current_price(self, symbol: str) -> float:
        tick = self.mt5.symbol_info_tick(symbol)
        return float(tick.bid)

    def account_balance(self) -> float:
        info = self.mt5.account_info()
        return float(info.balance)

    def open_positions(self, symbol: str) -> int:
        positions = self.mt5.positions_get(symbol=symbol)
        return len(positions) if positions else 0

    def lot_size_for_risk(self, symbol: str, stop_distance: float, risk_percent: float) -> float:
        balance = self.account_balance()
        risk_amount = balance * (risk_percent / 100.0)
        info = self.mt5.symbol_info(symbol)
        tick_value = info.trade_tick_value or 1.0
        tick_size = info.trade_tick_size or 0.0001
        ticks = stop_distance / tick_size if tick_size else 1
        raw_lots = risk_amount / (ticks * tick_value) if ticks and tick_value else 0.01
        step = info.volume_step or 0.01
        lots = max(info.volume_min, round(raw_lots / step) * step)
        return min(lots, info.volume_max)

    def place_order(self, symbol: str, direction: str, entry: float,
                     stop_loss: float, take_profit: float, lots: float) -> dict:
        order_type = self.mt5.ORDER_TYPE_BUY if direction == "buy" else self.mt5.ORDER_TYPE_SELL
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots,
            "type": order_type,
            "price": entry,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 20,
            "magic": config.MAGIC_NUMBER,
            "comment": "SNRZ-RONIN-SMC bot",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }
        result = self.mt5.order_send(request)
        return result._asdict() if hasattr(result, "_asdict") else dict(result)

    def shutdown(self):
        self.mt5.shutdown()
