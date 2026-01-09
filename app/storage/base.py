# app/storage/base.py
"""
Storage provider interface for raw article content.

Design principles:
- Raw article bodies stored in object storage (S3), not Postgres
- Content compressed before upload (gzip)
- Postgres stores only metadata + S3 references
- API reads/writes S3 server-side; clients never access S3 directly
- Lifecycle-aware: raw blobs may expire, metadata persists
"""

import gzip
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class ContentType(str, Enum):
    """Supported content types for raw storage."""
    TEXT_PLAIN = "text/plain"
    TEXT_HTML = "text/html"
    APPLICATION_JSON = "application/json"


class ContentEncoding(str, Enum):
    """Supported content encodings."""
    GZIP = "gzip"
    IDENTITY = "identity"  # No compression


@dataclass
class StorageMetadata:
    """Metadata about stored content."""
    uri: str  # S3 object key/path
    content_hash: str  # SHA256 of original (uncompressed) content
    content_type: ContentType
    content_encoding: ContentEncoding
    size_bytes: int  # Compressed size
    original_size_bytes: int  # Uncompressed size
    uploaded_at: datetime
    expires_at: Optional[datetime] = None  # For lifecycle management
    custom_metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class StorageObject:
    """A stored object with content and metadata."""
    content: bytes  # Decompressed content
    metadata: StorageMetadata
    exists: bool = True


def compute_content_hash(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def compress_content(content: bytes) -> bytes:
    """Compress content using gzip."""
    return gzip.compress(content, compresslevel=6)


def decompress_content(content: bytes) -> bytes:
    """Decompress gzip content."""
    return gzip.decompress(content)


class StorageProvider(ABC):
    """
    Abstract interface for object storage.

    Implementations must handle:
    - Upload with automatic compression
    - Download with automatic decompression
    - Lifecycle management (expiration)
    - Graceful handling of expired/deleted content
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 's3', 'local')."""
        pass

    @abstractmethod
    def upload(
        self,
        key: str,
        content: bytes,
        content_type: ContentType = ContentType.TEXT_PLAIN,
        expires_days: Optional[int] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> StorageMetadata:
        """
        Upload content to storage.

        Args:
            key: Object key/path (e.g., "raw/2024/01/06/story-uuid.txt.gz")
            content: Raw content bytes (will be compressed)
            content_type: MIME type of original content
            expires_days: Days until content expires (None = no expiration)
            metadata: Custom metadata to attach

        Returns:
            StorageMetadata with upload details
        """
        pass

    @abstractmethod
    def download(self, key: str) -> Optional[StorageObject]:
        """
        Download content from storage.

        Args:
            key: Object key/path

        Returns:
            StorageObject with decompressed content, or None if not found/expired
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if object exists."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete object from storage.

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def get_metadata(self, key: str) -> Optional[StorageMetadata]:
        """
        Get metadata without downloading content.

        Returns:
            StorageMetadata or None if not found
        """
        pass

    def generate_key(
        self,
        story_id: str,
        field: str = "body",
        timestamp: Optional[datetime] = None,
    ) -> str:
        """
        Generate a storage key for a story's raw content.

        Format: raw/{year}/{month}/{day}/{story_id}_{field}.txt.gz
        """
        ts = timestamp or datetime.utcnow()
        return f"raw/{ts.year}/{ts.month:02d}/{ts.day:02d}/{story_id}_{field}.txt.gz"
