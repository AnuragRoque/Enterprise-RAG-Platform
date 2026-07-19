import unittest
from ingestion.chunker import StructureAwareChunker

class TestChunker(unittest.TestCase):
    def test_chunker_does_not_split_mid_sentence(self):
        chunker = StructureAwareChunker(target_tokens=20, overlap_tokens=5)
        text = "This is the first sentence. This is the second sentence, which is a bit longer and has more words to test the token limits. Here is a third sentence. And a fourth one to ensure we get multiple chunks."
        
        chunks = chunker.chunk_text(text)
        
        self.assertTrue(len(chunks) > 1)
        
        # We expect chunks to end with sentence punctuation (., !, ?)
        for chunk in chunks:
            chunk = chunk.strip()
            self.assertTrue(chunk.endswith(('.', '!', '?')), f"Chunk doesn't end with punctuation: {chunk}")
            
if __name__ == "__main__":
    unittest.main()
