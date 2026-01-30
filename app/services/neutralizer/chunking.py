# app/services/neutralizer/chunking.py
"""
Article chunking for improved span detection on long articles.

Long articles (8000+ characters) suffer from "lost in the middle" phenomenon
where LLMs pay less attention to content in the middle sections.

This module splits articles into overlapping chunks to ensure all content
gets equal attention during span detection.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)


# Default chunk configuration
DEFAULT_CHUNK_SIZE = 3000  # Characters per chunk
DEFAULT_OVERLAP_SIZE = 500  # Overlap between chunks
MIN_CHUNK_SIZE = 1000  # Don't create tiny chunks


@dataclass
class ArticleChunk:
    """A chunk of article text with position metadata."""
    text: str
    start_offset: int  # Where this chunk starts in the original body
    end_offset: int    # Where this chunk ends in the original body
    chunk_index: int   # 0-based index of this chunk


class ArticleChunker:
    """
    Splits long articles into overlapping chunks for improved LLM attention.

    Features:
    - Configurable chunk size and overlap
    - Sentence boundary detection (doesn't split mid-sentence)
    - Paragraph boundary preference (tries to split between paragraphs)
    - Overlap regions to catch phrases at chunk boundaries
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap_size: int = DEFAULT_OVERLAP_SIZE
    ):
        """
        Initialize the chunker.

        Args:
            chunk_size: Target size of each chunk in characters
            overlap_size: Overlap between consecutive chunks
        """
        self.chunk_size = chunk_size
        self.overlap_size = overlap_size
        # Sentence ending patterns
        self._sentence_end = re.compile(r'[.!?][\s\n]+')
        # Paragraph break patterns
        self._para_break = re.compile(r'\n\n+')

    def needs_chunking(self, body: str) -> bool:
        """
        Determine if an article needs to be chunked.

        Args:
            body: Article body text

        Returns:
            True if article is long enough to benefit from chunking
        """
        # Chunk if body is significantly longer than chunk size
        # (1.5x threshold to avoid unnecessary chunking for borderline cases)
        return len(body) > self.chunk_size * 1.5

    def chunk(self, body: str) -> List[ArticleChunk]:
        """
        Split article body into overlapping chunks.

        Args:
            body: Full article body text

        Returns:
            List of ArticleChunk objects
        """
        if not body:
            return []

        if not self.needs_chunking(body):
            # Single chunk for short articles
            return [ArticleChunk(
                text=body,
                start_offset=0,
                end_offset=len(body),
                chunk_index=0
            )]

        chunks = []
        current_pos = 0
        chunk_index = 0

        while current_pos < len(body):
            # Calculate target end position
            target_end = current_pos + self.chunk_size

            if target_end >= len(body):
                # Last chunk - take everything remaining
                chunk_text = body[current_pos:]
                chunks.append(ArticleChunk(
                    text=chunk_text,
                    start_offset=current_pos,
                    end_offset=len(body),
                    chunk_index=chunk_index
                ))
                break

            # Find best split point (prefer paragraph > sentence > word)
            split_pos = self._find_split_point(body, current_pos, target_end)

            # Extract chunk
            chunk_text = body[current_pos:split_pos]

            # Skip empty or tiny chunks
            if len(chunk_text.strip()) < MIN_CHUNK_SIZE // 2:
                current_pos = split_pos
                continue

            chunks.append(ArticleChunk(
                text=chunk_text,
                start_offset=current_pos,
                end_offset=split_pos,
                chunk_index=chunk_index
            ))

            chunk_index += 1

            # Move to next chunk position (with overlap)
            # Start the next chunk overlap_size characters before where this one ended
            next_start = split_pos - self.overlap_size

            # But ensure we're making forward progress
            if next_start <= current_pos:
                next_start = split_pos

            current_pos = next_start

        logger.info(
            f"[CHUNKING] Split {len(body)} char article into {len(chunks)} chunks "
            f"(avg {len(body) // max(len(chunks), 1)} chars each)"
        )

        return chunks

    def _find_split_point(self, body: str, start: int, target_end: int) -> int:
        """
        Find the best position to split the text.

        Tries to split at (in order of preference):
        1. Paragraph break (\\n\\n)
        2. Sentence end (.!?)
        3. Word boundary (space)

        Args:
            body: Full article body
            start: Start position of current chunk
            target_end: Target end position

        Returns:
            Actual end position for the chunk
        """
        # Search window: look back from target_end to find good split point
        search_start = max(start + MIN_CHUNK_SIZE, target_end - 500)
        search_end = min(target_end + 200, len(body))  # Allow slight overshoot

        search_region = body[search_start:search_end]

        # 1. Try to find paragraph break
        para_match = None
        for match in self._para_break.finditer(search_region):
            para_match = match
            break  # Take first paragraph break in the region

        if para_match:
            return search_start + para_match.end()

        # 2. Try to find sentence end
        sentence_matches = list(self._sentence_end.finditer(search_region))
        if sentence_matches:
            # Prefer sentence end closest to target
            best_match = min(
                sentence_matches,
                key=lambda m: abs((search_start + m.end()) - target_end)
            )
            return search_start + best_match.end()

        # 3. Fall back to word boundary (space)
        space_pos = search_region.rfind(' ')
        if space_pos > 0:
            return search_start + space_pos + 1

        # 4. Last resort: split at target
        return min(target_end, len(body))

    def get_chunk_boundaries(self, body: str) -> List[Tuple[int, int]]:
        """
        Get chunk boundaries without creating full chunk objects.

        Useful for planning parallel processing.

        Args:
            body: Full article body

        Returns:
            List of (start, end) tuples for each chunk
        """
        chunks = self.chunk(body)
        return [(c.start_offset, c.end_offset) for c in chunks]


def chunk_article(
    body: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_size: int = DEFAULT_OVERLAP_SIZE
) -> List[ArticleChunk]:
    """
    Convenience function to chunk an article.

    Args:
        body: Article body text
        chunk_size: Target chunk size in characters
        overlap_size: Overlap between chunks

    Returns:
        List of ArticleChunk objects
    """
    chunker = ArticleChunker(chunk_size=chunk_size, overlap_size=overlap_size)
    return chunker.chunk(body)
