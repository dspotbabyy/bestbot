# lzb_bot_v2.py - Liquidity Zone Reversion Bot (UPGRADED)
# ✅ Now includes: Daily trend filter, volume filter, SMA200 alignment

import ccxt
import time
import numpy as np
import pandas as pd
import logging
import requests
import os
from datetime import datetime

# -------------------------------
# CONFIGURATION
# -------------------------------
SYMBOL = os.getenv('SYMBOL', 'ETH/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '15m')
HTF_TIMEFRAME = '1d'  # Higher Time Frame for trend
RISK_PERCENT = float(os.getenv('RISK_PERCENT', '1.0'))
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', '1.2'))
TAKE_PROFIT_RATIO = float(os.getenv('TP_RATIO', '1.8'))
MIN_VOLUME_FACTOR = float(os.getenv('MIN_VOL_FACTOR', '1.0'))
RSI_OVERBOUGHT = int(os.getenv('RSI_OVERB', '75'))
RSI_OVERSOLD = int(os.getenv('RSI_OVERS', '25'))
WICK_RATIO = float(os.getenv('WICK_RATIO', '2.0'))
PAPER_TRADING = os.getenv('PAPER_TRADING', 'True').lower() == 'true'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Initialize exchange
exchange = ccxt.bybit({
    'apiKey': os.getenv('BYBIT_API_KEY'),
    'secret': os.getenv('BYBIT_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
    }
})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------
# UTILITY FUNCTIONS
# -------------------------------

def send_alert(message):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
            payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': f"🚨 LZR Bot: {message}"}
            requests.post(url, data=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram failed: {e}")

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_data(symbol, timeframe, limit=100):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    df['body'] = abs(df['close'] - df['open'])
    df['upper_wick'] = df['high'] - np.maximum(df['open'], df['close'])
    df['lower_wick'] = np.minimum(df['open'], df['close']) - df['low']
    df['wick_ratio_upper'] = df['upper_wick'] / (df['body'] + 1e-8)
    df['wick_ratio_lower'] = df['lower_wick'] / (df['body'] + 1e-8)
    df['avg_volume'] = df['volume'].rolling(20).mean()
    df['sma_200'] = df['close'].rolling(200).mean()
    df['rsi'] = calculate_rsi(df['close'])

    return df

def get_daily_trend(symbol):
    try:
        df_daily = get_data(symbol, '1d', 50)
        latest = df_daily.iloc[-1]
        close = latest['close']
        sma_200 = latest['sma_200']

        if pd.isna(sma_200):
            return 'unknown'

        if close > sma_200:
            return 'bullish'
        else:
            return 'bearish'
    except Exception as e:
        logger.error(f"Daily trend error: {e}")
        return 'unknown'

def get_balance(asset='USDT'):
    if PAPER_TRADING:
        return 1000.0
    try:
        balance = exchange.fetch_balance()
        return balance['free'].get(asset, 0)
    except Exception as e:
        logger.error(f"Balance fetch failed: {e}")
        return 0

def place_order(side, symbol, amount, stop_loss=None, take_profit=None):
    if PAPER_TRADING:
        logger.info(f"🟢 PAPER TRADE: {side.upper()} {amount:.4f} {symbol}")
        send_alert(f"Paper {side} {amount:.4f} {symbol}")
        return True

    try:
        order = exchange.create_market_buy_order(symbol, amount) if side == 'buy' \
            else exchange.create_market_sell_order(symbol, amount)
        logger.info(f"✅ Live {side} order placed: {amount:.4f} {symbol}")

        price = order['average']
        sl_price = price * (1 - STOP_LOSS_PCT / 100) if side == 'buy' else price * (1 + STOP_LOSS_PCT / 100)
        tp_price = price * (1 + TAKE_PROFIT_RATIO * STOP_LOSS_PCT / 100) if side == 'buy' \
            else price * (1 - TAKE_PROFIT_RATIO * STOP_LOSS_PCT / 100)

        # Optional: Add conditional orders for SL/TP on Bybit
        # (This part may require Bybit Futures API for full control)

        send_alert(f"✅ Live {side.upper()} {amount:.4f} {symbol}\nSL: {sl_price:.2f} | TP: {tp_price:.2f}")
        return True
    except Exception as e:
        logger.error(f"❌ Order failed: {e}")
        send_alert(f"❌ Order failed: {e}")
        return False

# -------------------------------
# MAIN STRATEGY LOGIC (UPGRADED)
# -------------------------------
def check_signal():
    try:
        df = get_data(SYMBOL, TIMEFRAME)
        daily_trend = get_daily_trend(SYMBOL)
        latest = df.iloc[-2]  # Avoid incomplete candle

        # 🔴 UPGRADE 2: Filter low volume
        if latest['volume'] < MIN_VOLUME_FACTOR * latest['avg_volume']:
            logger.info("Skipped: Low volume")
            return None

        # 🔴 UPGRADE 3: Avoid reversion if against daily SMA200 trend
        if daily_trend == 'bullish' and latest['close'] < latest['sma_200']:
            logger.info("Skipped: Price below 200-SMA in uptrend")
            return None

        # 🔴 UPGRADE 1: Only trade in direction of daily trend
        if daily_trend == 'bullish':
            # Only allow longs
            if (latest['wick_ratio_lower'] >= WICK_RATIO and
                latest['rsi'] < RSI_OVERSOLD and
                latest['close'] > latest['open']):
                balance = get_balance('USDT')
                price = latest['close']
                amount = (balance * (RISK_PERCENT / 100)) / (price * (STOP_LOSS_PCT / 100))
                amount = amount * 0.95
                logger.info(f"🔍 Bullish reversion signal (aligned with daily trend)")
                return {'side': 'buy', 'amount': amount}

        elif daily_trend == 'bearish':
            # Only allow shorts
            if (latest['wick_ratio_upper'] >= WICK_RATIO and
                latest['rsi'] > RSI_OVERBOUGHT and
                latest['close'] < latest['open']):
                balance = get_balance('ETH')
                price = latest['close']
                amount = (balance * (RISK_PERCENT / 100)) / (STOP_LOSS_PCT / 100)
                amount = amount * 0.95
                logger.info(f"🔍 Bearish reversion signal (aligned with daily trend)")
                return {'side': 'sell', 'amount': amount}

        return None

    except Exception as e:
        logger.error(f"Signal check error: {e}")
        return None

# -------------------------------
# MAIN LOOP
# -------------------------------
def main():
    logger.info("🟢 Liquidity Zone Reversion Bot v2 Started (Upgraded)")
    logger.info(f"Trading: {SYMBOL} | Trend Filter: Daily | Paper Mode: {PAPER_TRADING}")
    send_alert(f"🤖 LZR Bot v2 started for {SYMBOL} with daily trend filter")

    while True:
        try:
            signal = check_signal()
            if signal:
                place_order(signal['side'], SYMBOL, signal['amount'])
                time.sleep(600)  # Cool-down after trade
            else:
                logger.info("No signal...")
            time.sleep(300)  # Check every 5 min
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            send_alert(f"⚠️ Bot error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()