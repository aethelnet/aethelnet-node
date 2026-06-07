"""
PAPER: Prototype Completion for Few-Shot Learning
LINK: http://arxiv.org/abs/2108.05010v1

ABSTRACT:
Few-shot learning aims to recognize novel classes with few examples. Pre-training based methods effectively tackle the problem by pre-training a feature extractor and then fine-tuning it through the nearest centroid based meta-learning. However, results show that the fine-tuning step makes marginal improvements. In this paper, 1) we figure out the reason, i.e., in the pre-trained feature space, the base classes already form compact clusters while novel classes spread as groups with large variances, which implies that fine-tuning feature extractor is less meaningful; 2) instead of fine-tuning feature extractor, we focus on estimating more representative prototypes. Consequently, we propose a novel prototype completion based meta-learning framework. This framework first introduces primitive knowledge (i.e., class-level part or attribute annotations) and extracts representative features for seen attributes as priors. Second, a part/attribute transfer network is designed to learn to infer the representative features for unseen attributes as supplementary priors. Finally, a prototype completion network is devised to learn to complete prototypes with these priors. Moreover, to avoid the prototype completion error, we further develop a Gaussian based prototype fusion strategy that fuses the mean-based and completed prototypes by exploiting the unlabeled samples. Extensive experiments show that our method: (i) obtains more accurate prototypes; (ii) achieves superior performance on both inductive and transductive FSL settings.
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
