import numpy as np
from typing import List, Dict, Any

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Computes cosine similarity between a vector and a matrix of vectors."""
    dot_product = np.dot(b, a)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b, axis=1)
    # Handle division by zero
    similarity = dot_product / (norm_a * norm_b + 1e-10)
    return similarity

def maximal_marginal_relevance(
    query_embedding: List[float],
    chunk_embeddings: List[List[float]],
    relevance_scores: List[float],
    top_k: int = 6,
    lambda_param: float = 0.7
) -> List[int]:
    """
    Maximal Marginal Relevance (MMR)
    Balances relevance (relevance_scores) with diversity (cosine distance between embeddings).
    
    Args:
        query_embedding: Not strictly needed here if relevance_scores are provided by CrossEncoder, 
                         but keeping standard signature.
        chunk_embeddings: List of dense embeddings for the candidates.
        relevance_scores: List of scores for the candidates (e.g. from a CrossEncoder).
        top_k: Number of chunks to select.
        lambda_param: Controls relevance vs diversity. 
                      1.0 = purely relevance, 0.0 = purely diversity.
                      
    Returns:
        List of selected indices.
    """
    if not chunk_embeddings:
        return []

    # Convert to numpy for fast math
    embeddings = np.array(chunk_embeddings)
    scores = np.array(relevance_scores)
    
    # Normalize scores between 0 and 1 so they are comparable to cosine similarity
    if len(scores) > 1:
        min_score = np.min(scores)
        max_score = np.max(scores)
        if max_score > min_score:
            scores = (scores - min_score) / (max_score - min_score)
        else:
            scores = np.ones_like(scores)

    selected_indices = []
    unselected_indices = list(range(len(embeddings)))

    # Select the first chunk purely by relevance
    first_idx = int(np.argmax(scores))
    selected_indices.append(first_idx)
    unselected_indices.remove(first_idx)

    # Iteratively select the rest
    while len(selected_indices) < top_k and unselected_indices:
        unselected_embeddings = embeddings[unselected_indices]
        
        # Calculate similarity of all unselected to all currently selected
        max_similarity_to_selected = np.zeros(len(unselected_indices))
        for sel_idx in selected_indices:
            sel_emb = embeddings[sel_idx]
            sims = cosine_similarity(sel_emb, unselected_embeddings)
            max_similarity_to_selected = np.maximum(max_similarity_to_selected, sims)
            
        unselected_scores = scores[unselected_indices]
        
        # MMR formula
        mmr_scores = lambda_param * unselected_scores - (1 - lambda_param) * max_similarity_to_selected
        
        best_idx_relative = int(np.argmax(mmr_scores))
        best_idx_absolute = unselected_indices[best_idx_relative]
        
        selected_indices.append(best_idx_absolute)
        unselected_indices.remove(best_idx_absolute)

    return selected_indices
