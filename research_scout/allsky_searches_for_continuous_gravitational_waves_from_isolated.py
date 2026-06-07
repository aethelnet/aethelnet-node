"""
PAPER: All-sky Searches for Continuous Gravitational Waves from Isolated Neutron Stars in the Data from the First Part of the Fourth LIGO-Virgo-KAGRA Observing Run
LINK: http://arxiv.org/abs/2603.14168v1

ABSTRACT:
We present results from an all-sky search for continuous gravitational waves, using three different methods applied to the first eight months of LIGO data from the fourth LIGO-Virgo-KAGRA Collaboration s observing run. We aim at signals potentially emitted by rotating, non-axisymmetric isolated neutron star in the Milky Way. The analysis spans a frequency range from 20 Hz to 2000 Hz and accommodates frequency derivative magnitudes up to $10^{-8}$ Hz/s. No statistically significant periodic gravitational wave signals were detected. We establish 95% confidence-level (CL) frequentist upper limits on the dimensionless strain amplitudes. The most stringent population-averaged strain upper limits reach 9.7 $\times$ $10^{-26}$ near 290 Hz, matching the best previous constraints from 250 to $\sim$1700 Hz while extending coverage to a much broader spin-down range. At higher frequencies, the new limits improve upon previous results by factors of approximately $\sim$1.6. These constraints are applied to three astrophysical scenarios: 1) the distribution of galactic neutron stars as a function of spin frequency and ellipticity; 2) the contribution of millisecond pulsars to the GeV excess near the galactic center; and 3) the possible dark matter fraction composed of nearby inspiraling primordial binary black holes with asteroid-scale masses.
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
