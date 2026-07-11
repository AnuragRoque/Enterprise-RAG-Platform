import requests
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential
from core.config import settings
import logging

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        self.provider = settings.default_llm_provider
        self.model = settings.embedding_model
        self.base_url = settings.ollama_base_url
        self.dimension = settings.embedding_dimension

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def embed_text(self, text: str) -> List[float]:
        """Get embedding for a single text chunk with retry logic"""
        if self.provider == "ollama":
            url = f"{self.base_url}/api/embeddings"
            response = requests.post(url, json={
                "model": self.model,
                "prompt": text,
                # Keep the embedding model resident so it isn't swapped out against the
                # chat model between requests.
                "keep_alive": "30m"
            }, timeout=30)
            response.raise_for_status()
            return response.json()["embedding"]
        else:
            raise NotImplementedError(f"Embedding provider {self.provider} not implemented")

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a batch of texts. 
        Ollama currently does not support batch embedding in its API natively in the same way OpenAI does,
        so we embed them sequentially here, but this interface allows swapping to a provider that supports batching.
        """
        embeddings = []
        for text in texts:
            try:
                emb = self.embed_text(text)
                embeddings.append(emb)
            except Exception as e:
                logger.error(f"Failed to embed text chunk: {e}")
                # We could append a zero vector or raise depending on strictness
                raise e
        return embeddings
