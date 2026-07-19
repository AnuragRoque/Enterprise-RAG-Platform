import unittest
import numpy as np
from core.models import DocumentChunk
from retrieval.engine import compute_rrf
from retrieval.mmr import maximal_marginal_relevance, cosine_similarity

class TestRetrieval(unittest.TestCase):
    
    def test_rrf_logic(self):
        # Create mock chunks
        c1 = DocumentChunk(id=1, text="Chunk 1")
        c2 = DocumentChunk(id=2, text="Chunk 2")
        c3 = DocumentChunk(id=3, text="Chunk 3")
        c4 = DocumentChunk(id=4, text="Chunk 4")
        
        # Dense search returns 1, 2, 3
        list_a = [c1, c2, c3]
        # Sparse search returns 3, 4, 1
        list_b = [c3, c4, c1]
        
        # 1 gets rank 0 + rank 2
        # 3 gets rank 2 + rank 0
        # 2 gets rank 1
        # 4 gets rank 1
        
        fused = compute_rrf([list_a, list_b], k=1)
        
        # Ensure all 4 unique chunks are present
        self.assertEqual(len(fused), 4)
        
        # 1 and 3 should be at the top because they appear in both lists
        self.assertTrue(fused[0].id in [1, 3])
        self.assertTrue(fused[1].id in [1, 3])

    def test_cosine_similarity(self):
        v1 = np.array([1.0, 0.0])
        v2 = np.array([1.0, 0.0])
        v3 = np.array([0.0, 1.0])
        
        sim1 = cosine_similarity(v1, np.array([v2]))
        self.assertAlmostEqual(sim1[0], 1.0, places=5)
        
        sim2 = cosine_similarity(v1, np.array([v3]))
        self.assertAlmostEqual(sim2[0], 0.0, places=5)

    def test_mmr(self):
        # 4 chunks
        # Chunk 0 and Chunk 1 are highly relevant, but also highly similar to each other
        # Chunk 2 is moderately relevant, but totally orthogonal (diverse)
        
        query = [1.0, 0.0]
        embeddings = [
            [1.0, 0.0],  # Highly similar to 1
            [0.9, 0.1],  # Highly similar to 0
            [0.0, 1.0],  # Orthogonal
            [-1.0, 0.0]  # Opposite
        ]
        scores = [10.0, 9.9, 5.0, 1.0]
        
        # Pure relevance (lambda=1.0) -> should pick 0 and 1
        selected_rel = maximal_marginal_relevance(query, embeddings, scores, top_k=2, lambda_param=1.0)
        self.assertEqual(selected_rel, [0, 1])
        
        # Balance (lambda=0.5) -> after picking 0, 1 is penalized for similarity to 0. It should pick 2 instead.
        selected_div = maximal_marginal_relevance(query, embeddings, scores, top_k=2, lambda_param=0.5)
        self.assertEqual(selected_div, [0, 2])

if __name__ == "__main__":
    unittest.main()
