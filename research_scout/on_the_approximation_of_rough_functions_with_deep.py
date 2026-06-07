"""
PAPER: On the approximation of rough functions with deep neural networks
LINK: http://arxiv.org/abs/1912.06732v2

ABSTRACT:
Deep neural networks and the ENO procedure are both efficient frameworks for approximating rough functions. We prove that at any order, the ENO interpolation procedure can be cast as a deep ReLU neural network. This surprising fact enables the transfer of several desirable properties of the ENO procedure to deep neural networks, including its high-order accuracy at approximating Lipschitz functions. Numerical tests for the resulting neural networks show excellent performance for approximating solutions of nonlinear conservation laws and at data compression.
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
