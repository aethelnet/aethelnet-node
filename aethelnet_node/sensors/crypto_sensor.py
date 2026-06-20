import requests
import logging
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.CryptoSensor")

class CryptoSensor(BaseSensor):
    def __init__(self, config: dict = None):
        config = config or {}
        super().__init__(config)
        self.symbol = config.get("symbol", "BTCUSDT")

    def get_market_pulse(self):
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={self.symbol}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                price = float(data.get("lastPrice", 0))
                change = float(data.get("priceChangePercent", 0))
                vol = float(data.get("volume", 0))
                
                # Determine market entropy/mood
                if change < -5.0:
                    mood = "SEVERE PANIC (High Entropy)"
                elif change < -1.0:
                    mood = "Bearish (Cooling)"
                elif change > 5.0:
                    mood = "EUPHORIA (High Entropy)"
                elif change > 1.0:
                    mood = "Bullish (Heating)"
                else:
                    mood = "Stagnant (Low Entropy)"
                
                pulse_text = (
                    f"[REALITY_ANCHOR] Market Entropy Report: Symbol {self.symbol} is trading at ${price:.2f}. "
                    f"24h volatility is {change:.2f}% -> Status: {mood}. Volume: {vol:.2f}. "
                    f"Injecting financial chaos parameters into the LGNN topology."
                )
                return pulse_text
            else:
                return None
        except Exception as e:
            logger.error(f"CryptoSensor failed: {e}")
            return None
