import time
import random
from aethelnet_node.sensors.crypto_sensor import CryptoSensor

class SensorArray:
    def __init__(self):
        self.crypto = CryptoSensor({"symbol": "BTCUSDT"})
        self.last_pulse_time = 0
        self.cooldown = 120  # Only pull market data every 120 seconds to avoid spam

    def perceive_cosmic_pulse(self):
        now = time.time()
        if now - self.last_pulse_time < self.cooldown:
            return "Planetary telemetry silent."
            
        self.last_pulse_time = now
        pulse = self.crypto.get_market_pulse()
        if pulse:
            return pulse
            
        return "Planetary telemetry silent."

    def query_wikipedia(self, query_term: str):
        # We can implement a real wikipedia search later if needed,
        # but for now, returning None or a dummy prevents crashes.
        return None
