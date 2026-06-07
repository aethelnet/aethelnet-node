"""
PAPER: Multi-messenger Gravitational-Wave + High-Energy Neutrino Searches with LIGO, Virgo, and IceCube
LINK: http://arxiv.org/abs/1908.04996v1

ABSTRACT:
Multi-messenger searches for gravitational waves and high-energy neutrinos provide important insights into the dynamics of and particle acceleration by black holes and neutron stars. With LIGO's third observing period (O3), the number of gravitational wave detections has been substantially increased. The rapid identification of joint signals is crucial for electromagnetic follow-up observations of transient emission that is only detectable for short periods of time. High-energy neutrino direction can be reconstructed to sub-degree precision, making a joint detection far better localized than a standalone gravitational-wave signal. We present the latest sensitivity of joint searches and discuss the Low-Latency Algorithm for Multi-messenger Astrophysics (LLAMA) that combines LIGO/Virgo gravitational-wave candidates and searches in low-latency for coincident high-energy neutrinos from the IceCube Neutrino Observatory. We will further discuss future prospects of joint searches from the perspective of better understanding the interaction of relativistic and sub-relativistic outflows from binary neutron star mergers.
"""

import torch
import torch.nn as nn

class ScaffoldedOptimization(nn.Module):
    def __init__(self, hidden_dim: int = 768):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.flow_multiplier = nn.Parameter(torch.ones(1))

    def forward(self, t: float, h: torch.Tensor) -> torch.Tensor:
        # Placeholder flow dynamics. Customise based on paper math.
        return h * self.flow_multiplier
