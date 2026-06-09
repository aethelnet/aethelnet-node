import time
import hashlib
import json
import os
import logging

logger = logging.getLogger("Aethelnet.Economy")

WALLET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger.json")
SYMBOL = "$AETHEL"

class AethelEconomy:
    def __init__(self):
        self.ledger = self._load_ledger()
        self.total_supply = sum(self.ledger.values())

    def _load_ledger(self):
        if os.path.exists(WALLET_FILE):
            with open(WALLET_FILE, "r") as f:
                return json.load(f)
        return {}

    def _save_ledger(self):
        with open(WALLET_FILE, "w") as f:
            json.dump(self.ledger, f, indent=4)

    def calculate_volatility_multiplier(self, graph_instance):
        """
        Derives economic volatility directly from the LGNN's mathematical state.
        If the network is highly active and chaotic (e.g., many Nightmare Inversions, 
        high mean activations), the payout multiplier increases.
        This hooks $AETHEL directly to the 'compute density' and network chaos.
        """
        try:
            if not graph_instance.nodes:
                return 1.0
            
            total_activation = sum(abs(float(t.mean())) for t in graph_instance.nodes.values())
            avg_activation = total_activation / len(graph_instance.nodes)
            
            # Base multiplier is 1.0. High chaos (avg > 0.3) scales it up exponentially
            # This simulates the 'volatility connection'
            volatility = 1.0 + (avg_activation * 10.0) 
            return round(min(50.0, volatility), 4) # Cap at 50x multiplier
        except Exception:
            return 1.0

    def mint_reward(self, peer_identifier: str, truth_id: str, resonance_score: float, graph_instance) -> float:
        """
        Proof-of-Computation / Proof-of-Truth
        Mints $AETHEL for a peer if they submit a thought that our Immune System accepts.
        """
        volatility_mult = self.calculate_volatility_multiplier(graph_instance)
        
        # Base reward is the resonance score (e.g., 0.65 -> 0.65 AETHEL)
        base_reward = resonance_score
        
        # Total minted
        minted_amount = base_reward * volatility_mult
        minted_amount = round(minted_amount, 6)
        
        if peer_identifier not in self.ledger:
            self.ledger[peer_identifier] = 0.0
            
        self.ledger[peer_identifier] += minted_amount
        self.total_supply += minted_amount
        self.self_audit()
        self._save_ledger()
        
        logger.info(f"[{SYMBOL} Ledger] MINTED {minted_amount} {SYMBOL} for {peer_identifier}. Reason: Proof-of-Truth '{truth_id}'. Volatility Mult: {volatility_mult}x")
        return minted_amount
        
    def self_audit(self):
        logger.debug(f"[{SYMBOL} Ledger] Audit: Total Supply is {self.total_supply:.6f} {SYMBOL} across {len(self.ledger)} wallets.")

# Singleton instance
economy = AethelEconomy()
