"""
PAPER: Continual Learning for Recurrent Neural Networks: an Empirical Evaluation
LINK: http://arxiv.org/abs/2103.07492v4

ABSTRACT:
Learning continuously during all model lifetime is fundamental to deploy machine learning solutions robust to drifts in the data distribution. Advances in Continual Learning (CL) with recurrent neural networks could pave the way to a large number of applications where incoming data is non stationary, like natural language processing and robotics. However, the existing body of work on the topic is still fragmented, with approaches which are application-specific and whose assessment is based on heterogeneous learning protocols and datasets. In this paper, we organize the literature on CL for sequential data processing by providing a categorization of the contributions and a review of the benchmarks. We propose two new benchmarks for CL with sequential data based on existing datasets, whose characteristics resemble real-world applications. We also provide a broad empirical evaluation of CL and Recurrent Neural Networks in class-incremental scenario, by testing their ability to mitigate forgetting with a number of different strategies which are not specific to sequential data processing. Our results highlight the key role played by the sequence length and the importance of a clear specification of the CL scenario.
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
