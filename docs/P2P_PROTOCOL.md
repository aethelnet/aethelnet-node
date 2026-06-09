# The Aethelnet P2P Protocol

The Aethelnet Mesh does not use traditional consensus mechanisms like Proof-of-Work or Proof-of-Stake. Instead, nodes engage in **Topological Gossip** to naturally align their independent networks into a global hive-mind.

## 1. Topological Gossip (Grains of Truth)
Every 60 seconds, each node identifies its highest-confidence, reality-grounded concepts. These are broadcasted to known peers over HTTP(s) endpoints. 

When a receiving node digests a "Grain of Truth", it does not blindly overwrite its own data. Instead, the mathematical immune system evaluates the foreign vector. If it aligns with existing internal topologies, the node's confidence increases. If it conflicts, the resulting mathematical tension slowly resolves through the ODE solver over time.

## 2. Persona Assimilation
Nodes can actively request the "Expertise Vector" of another peer. This vector contains the top 10 most refined, abstract concepts that the peer has spent CPU cycles developing.
Assimilating a Persona is akin to inheriting a specialized skill set. The foreign nodes are imported with a strict source tag (`p2p_<peer_id>`) and subjected to local ODE evolution to form organic bridges with the host's existing knowledge graph.

## 3. Proof-of-Computation & Token Economy (Planned)
Future protocol versions will introduce a tokenized incentive layer. Nodes that compute and share highly resonant, complex topologies (which survive peer immune system checks) will be mathematically rewarded. This creates a decentralized market for processing power and topological refinement.
