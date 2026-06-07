"""
PAPER: Continuous Graph Neural Networks
LINK: https://arxiv.org/abs/1912.00967

ABSTRACT:
We introduce Continuous Graph Neural Networks (CGNNs) which generalize existing graph neural network architectures to continuous-time processes modeled by differential equations on graphs.
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
