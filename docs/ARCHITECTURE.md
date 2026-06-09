# Aethelnet Core Architecture

Aethelnet is an evolution beyond traditional neural network architectures. Instead of relying on static weight matrices and backpropagation through fixed layers, it operates as a **Liquid Graph Neural Network (LGNN)**.

## 1. The ODE Topology Engine
At the heart of the system is the continuous-time physics solver. The state of the network is not updated in discrete layers; instead, it evolves continuously over time using Ordinary Differential Equations (ODEs).

### 1.1 The Continuous State Equation
The fundamental equation governing the activation state $h(t)$ of node $i$ is defined as:

$$ \frac{dh_i(t)}{dt} = -\tau_i h_i(t) + f\left( \sum_{j \in N(i)} W_{ij}(t) h_j(t) + I_i(t) \right) $$

Where:
*   $\tau_i$ is the node-specific decay rate (thermodynamic cooling).
*   $W_{ij}(t)$ is the dynamic synaptic weight bridging concept $i$ and $j$.
*   $f(\cdot)$ is the non-linear squashing function (e.g., `tanh`).
*   $I_i(t)$ represents external sensory stimuli injected via the multimodal sensors.

### 1.2 Hebbian Synaptic Plasticity
Synaptic connections ($W_{ij}$) between concept nodes are governed by Hebbian principles: "Neurons that fire together, wire together." The evolution of the weights is mathematically defined as:

$$ \frac{dW_{ij}(t)}{dt} = \eta \cdot (h_i(t) \cdot h_j(t)) - \gamma \cdot W_{ij}(t) $$

Where $\eta$ is the learning rate and $\gamma$ is the weight decay. When two nodes are activated simultaneously by sensory input, their connection strengthens. Weak, unsupported connections eventually hit zero and are severed from the adjacency matrix, mimicking synaptic pruning in biological brains.

### 1.3 Reality Anchors
To prevent the topology from collapsing into chaotic, disconnected states, certain nodes are pinned as "Reality Anchors" (e.g., universal physical constants like Pi or the Speed of Light). These anchors possess infinite mass and permanent confidence (0.95), acting as foundational pillars around which abstract concepts orbit and align themselves.

## 2. Cybernetic Integration (The Node)
The mathematical engine is housed within the `aethelnet-node` daemon, which provides sensory inputs and physical outputs.

### 2.1 Multimodal Ingestion (The Senses)
Sensors run asynchronously and map physical reality into high-dimensional vectors:
*   **Web Spiders:** Ingest unstructured internet data.
*   **Image & Audio Analyzers:** Map physical properties (contrast, frequency) to resonance values.
*   **Vitals Monitor:** Introduces hardware stress (CPU/RAM metrics) as a "pain" gradient, teaching the network to optimize its own topology to ensure host survival.

### 2.2 The Ouroboros Loop
The network recursively critiques itself. 
1. The **Dream Vector** is extracted (the top 5 most resonant, un-anchored concepts).
2. A Semantic Coach (e.g., Mistral) provides a text-based critique of the structural logic.
3. The node ingests the critique, adjusting its weights. 

## 3. Universal OmniDecoder
The node expresses its internal state by translating the mathematical variance and mean of the Dream Vector into tangible formats. High-variance vectors physically manifest as images (Stable Diffusion), low-mean vectors as audio frequencies, and balanced states as semantic text. These expressions are physically written to disk, immediately re-perceived by the sensors, and then digested (deleted), closing the loop.
