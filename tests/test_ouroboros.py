import os
import unittest
import torch
from unittest.mock import patch
from aethelnet_node.main import graph_instance, node_metrics
from aethelnet_node.ouroboros import OuroborosLoop
from aethelnet_node.database import init_db


class TestOuroborosLoop(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        init_db()
        self.loop = OuroborosLoop()
        # Seed graph with some test concepts
        v1 = torch.zeros(768)
        v1[0] = 2.0  # High energy

        v2 = torch.zeros(768)
        v2[1] = 1.0

        v3 = torch.zeros(768)
        v3[2] = 0.5

        graph_instance.add_node("Concept_HighEnergy", v1)
        graph_instance.add_node("Concept_MediumEnergy", v2, connections=["Concept_HighEnergy"])
        graph_instance.add_node("Concept_LowEnergy", v3)

        node_metrics["Concept_HighEnergy"] = {"confidence": 0.9, "is_grounded": False}
        node_metrics["Concept_MediumEnergy"] = {"confidence": 0.8, "is_grounded": False}
        node_metrics["Concept_Grounded"] = {"confidence": 0.99, "is_grounded": True}
        graph_instance.add_node("Concept_Grounded", torch.randn(768))

    async def test_extract_dream_concepts(self):
        dream = await self.loop.extract_dream_concepts()
        self.assertIsInstance(dream, list)
        self.assertGreater(len(dream), 0)
        # Grounded node must NOT be part of the dream
        self.assertNotIn("Concept_Grounded", dream)
        # High energy node should be top
        self.assertEqual(dream[0], "Concept_HighEnergy")

    async def test_query_coach_live(self):
        dream = ["Concept_HighEnergy", "Concept_MediumEnergy"]
        critique = await self.loop.query_coach(dream)
        self.assertIsNotNone(critique)
        self.assertIsInstance(critique, str)
        self.assertGreater(len(critique), 10)

    async def test_query_coach_offline_fallback(self):
        dream = ["Concept_HighEnergy", "Concept_MediumEnergy"]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "OPENROUTER_API_KEY": ""}):
            offline_critique = await self.loop.query_coach(dream)
            self.assertIsNotNone(offline_critique)
            self.assertIn("Topological", offline_critique)

    async def test_ingest_feedback(self):
        feedback = "The connection between Concept_HighEnergy and Concept_MediumEnergy forms an orthogonal basis."
        success = await self.loop.ingest_feedback(feedback)
        self.assertTrue(success)

        # Verify a new observation node was created
        coach_nodes = [nid for nid in graph_instance.nodes.keys() if "Ouroboros_Coach" in graph_instance._original_id(nid)]
        self.assertGreater(len(coach_nodes), 0)


if __name__ == "__main__":
    unittest.main()
