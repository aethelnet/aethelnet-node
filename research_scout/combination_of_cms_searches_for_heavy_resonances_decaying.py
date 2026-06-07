"""
PAPER: Combination of CMS searches for heavy resonances decaying to pairs of bosons or leptons
LINK: http://arxiv.org/abs/1906.00057v2

ABSTRACT:
A statistical combination of searches for heavy resonances decaying to pairs of bosons or leptons is presented. The data correspond to an integrated luminosity of 35.9 fb$^{-1}$ collected during 2016 by the CMS experiment at the LHC in proton-proton collisions at a center-of-mass energy of 13 TeV. The data are found to be consistent with expectations from the standard model background. Exclusion limits are set in the context of models of spin-1 heavy vector triplets and of spin-2 bulk gravitons. For mass-degenerate W' and Z' resonances that predominantly couple to the standard model gauge bosons, the mass exclusion at 95% confidence level of heavy vector bosons is extended to 4.5 TeV as compared to 3.8 TeV determined from the best individual channel. This excluded mass increases to 5.0 TeV if the resonances couple predominantly to fermions.
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
