"""
Main loop: for every symbol, on every poll:
  1. Pull analysis-timeframe candles + confirmation-timeframe candles from MT5
  2. Compute today's FOP/NOP/DOP session levels
  3. Run the SNRZ + RONIN + SMC confirmation engine
  4. If a signal appears and no position is already open on that symbol,
     size the trade by risk % and send it to MT5
"""

import logging
import sys
import time

from . import config, confirmation, levels
from .executor import MT5Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("snrz-bot")


def run_once(client: MT5Client, symbol: str):
    analysis_candles = client.get_candles(symbol, config.ANALYSIS_TF, count=300)
    confirm_candles = client.get_candles(symbol, config.CONFIRMATION_TF, count=150)
    if not analysis_candles or not confirm_candles:
        log.warning("[%s] no candle data yet", symbol)
        return

    price = client.current_price(symbol)
    daily_open = client.get_daily_open(symbol)
    hourly_bars = client.get_hourly_bars_today(symbol)
    session_levels = levels.compute_session_levels(
        daily_open, hourly_bars, config.FOP_UTC_HOUR, config.NOP_UTC_HOUR
    )

    if client.open_positions(symbol) >= config.MAX_OPEN_TRADES_PER_SYMBOL:
        log.info("[%s] already has an open position, skipping", symbol)
        return

    signal = confirmation.build_signal(
        symbol=symbol,
        candles_analysis=analysis_candles,
        candles_confirmation=confirm_candles,
        current_price=price,
        session_levels=session_levels,
    )

    if not signal:
        log.info("[%s] no confirmed signal at %.5f", symbol, price)
        return

    stop_distance = abs(signal.entry - signal.stop_loss)
    lots = client.lot_size_for_risk(symbol, stop_distance, config.RISK_PERCENT_PER_TRADE)

    log.info("[%s] SIGNAL %s @ %.5f | SL %.5f | TP %.5f | lots %.2f | %s",
              symbol, signal.direction.upper(), signal.entry,
              signal.stop_loss, signal.take_profit, lots, signal.reason)

    result = client.place_order(symbol, signal.direction, signal.entry,
                                 signal.stop_loss, signal.take_profit, lots)
    log.info("[%s] order result: %s", symbol, result)


def main():
    log.info("Connecting to MT5 bridge at %s:%s ...", config.MT5_BRIDGE_HOST, config.MT5_BRIDGE_PORT)
    client = MT5Client()
    log.info("Connected. Trading symbols: %s", config.SYMBOLS)

    try:
        while True:
            for symbol in config.SYMBOLS:
                try:
                    run_once(client, symbol)
                except Exception as e:
                    log.exception("[%s] error during run_once: %s", symbol, e)
            time.sleep(config.POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
