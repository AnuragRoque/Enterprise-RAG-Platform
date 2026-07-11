import tiktoken
import nltk
from typing import List
import logging

logger = logging.getLogger(__name__)

try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    logger.info("Downloading NLTK punkt tokenizer...")
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)

class StructureAwareChunker:
    def __init__(self, target_tokens: int = 600, overlap_tokens: int = 90, encoding_name: str = "cl100k_base"):
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.encoder = tiktoken.get_encoding(encoding_name)

    def count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def chunk_text(self, text: str) -> List[str]:
        """
        Chunks text strictly along sentence boundaries while attempting to stay within target_tokens.
        """
        # First, split by double newlines to try to preserve paragraph structure
        paragraphs = text.split('\n\n')
        
        sentences = []
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            # Split paragraph into sentences
            p_sentences = nltk.tokenize.sent_tokenize(p)
            sentences.extend(p_sentences)

        chunks = []
        current_chunk = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self.count_tokens(sentence)
            
            # If a single sentence is larger than our target, we are forced to split it or just add it.
            # Usually, sentences are small. If it's huge, we just add it to avoid infinite loops,
            # though advanced logic could split by words here.
            
            if current_tokens + sentence_tokens > self.target_tokens and current_chunk:
                # Store the current chunk
                chunks.append(" ".join(current_chunk))
                
                # Create overlap for the next chunk
                # We backtrack to find sentences to overlap
                overlap_chunk = []
                overlap_count = 0
                for overlap_sentence in reversed(current_chunk):
                    s_toks = self.count_tokens(overlap_sentence)
                    if overlap_count + s_toks > self.overlap_tokens and overlap_chunk:
                        break
                    overlap_chunk.insert(0, overlap_sentence)
                    overlap_count += s_toks
                
                current_chunk = overlap_chunk
                current_tokens = overlap_count
            
            current_chunk.append(sentence)
            current_tokens += sentence_tokens
            
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks
