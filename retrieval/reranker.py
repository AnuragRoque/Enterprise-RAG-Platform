import logging
from typing import List, Tuple
import torch
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

class CrossEncoderService:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initializes the cross-encoder model. 
        Downloads the model on first run.
        """
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading Cross-Encoder model '{model_name}' on {self.device}...")
        self.model = CrossEncoder(model_name, device=self.device)
        logger.info("Cross-Encoder model loaded successfully.")

    def score_pairs(self, query: str, texts: List[str]) -> List[float]:
        """
        Scores a list of (query, text) pairs.
        Returns a list of relevance scores (higher is better).
        """
        if not texts:
            return []
            
        pairs = [[query, text] for text in texts]
        scores = self.model.predict(pairs)
        
        # Convert numpy array to list of floats for easier downstream handling
        return scores.tolist()
