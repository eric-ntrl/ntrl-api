# app/storage/local_provider.py
"""
Local filesystem storage provider for development and testing.

Mimics S3 behavior but stores files locally.
NOT for production use.
"""

import json
import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.storage.base import (
    ContentEncoding,
    ContentType,
    StorageMetadata,
    StorageObject,
    StorageProvider,
    compress_content,
    compute_content_hash,
    decompress_content,
)

logger = logging.getLogger(__name__)


class LocalStorageProvider(StorageProvider):
    """
    Local filesystem storage provider.

    Stores files in a directory structure that mimics S3.
    Useful for development and testing without S3 access.

    Configuration:
    - LOCAL_STORAGE_PATH: Base directory (default: ./storage)
    """

    def __init__(self, base_path: str | None = None):
        """
        Initialize local storage.

        Args:
            base_path: Base directory for storage (or LOCAL_STORAGE_PATH env)
        """
        self._base_path = Path(base_path or os.getenv("LOCAL_STORAGE_PATH", "./storage"))
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._metadata_suffix = ".meta.json"

        logger.info(f"Local storage initialized: {self._base_path}")

    @property
    def name(self) -> str:
        return "local"

    def _get_path(self, key: str) -> Path:
        """Get filesystem path for key, with path traversal protection."""
        resolved = (self._base_path / key).resolve()
        if not resolved.is_relative_to(self._base_path.resolve()):
            raise ValueError("Path traversal detected")
        return resolved

    def _get_metadata_path(self, key: str) -> Path:
        """Get metadata file path for key, with path traversal protection."""
        resolved = (self._base_path / f"{key}{self._metadata_suffix}").resolve()
        if not resolved.is_relative_to(self._base_path.resolve()):
            raise ValueError("Path traversal detected")
        return resolved

    def upload(
        self,
        key: str,
        content: bytes,
        content_type: ContentType = ContentType.TEXT_PLAIN,
        expires_days: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StorageMetadata:
        """Upload content to local filesystem."""
        # Compute hash and compress
        content_hash = compute_content_hash(content)
        original_size = len(content)
        compressed = compress_content(content)
        compressed_size = len(compressed)

        # Calculate expiration
        expires_at = None
        if expires_days:
            expires_at = datetime.now(UTC) + timedelta(days=expires_days)

        # Create directory structure
        file_path = self._get_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write compressed content
        file_path.write_bytes(compressed)

        # Build metadata
        storage_metadata = StorageMetadata(
            uri=key,
            content_hash=content_hash,
            content_type=content_type,
            content_encoding=ContentEncoding.GZIP,
            size_bytes=compressed_size,
            original_size_bytes=original_size,
            uploaded_at=datetime.now(UTC),
            expires_at=expires_at,
            custom_metadata=metadata or {},
        )

        # Write metadata file
        meta_path = self._get_metadata_path(key)
        meta_dict = {
            "uri": storage_metadata.uri,
            "content_hash": storage_metadata.content_hash,
            "content_type": storage_metadata.content_type.value,
            "content_encoding": storage_metadata.content_encoding.value,
            "size_bytes": storage_metadata.size_bytes,
            "original_size_bytes": storage_metadata.original_size_bytes,
            "uploaded_at": storage_metadata.uploaded_at.isoformat(),
            "expires_at": storage_metadata.expires_at.isoformat() if storage_metadata.expires_at else None,
            "custom_metadata": storage_metadata.custom_metadata,
        }
        meta_path.write_text(json.dumps(meta_dict, indent=2))

        logger.debug(f"Uploaded to local: {key}")
        return storage_metadata

    def download(self, key: str) -> StorageObject | None:
        """Download and decompress content from local filesystem."""
        file_path = self._get_path(key)
        if not file_path.exists():
            return None

        # Read compressed content
        compressed = file_path.read_bytes()
        content = decompress_content(compressed)

        # Read metadata
        metadata = self._load_metadata(key)
        if not metadata:
            # Create minimal metadata if missing
            metadata = StorageMetadata(
                uri=key,
                content_hash=compute_content_hash(content),
                content_type=ContentType.TEXT_PLAIN,
                content_encoding=ContentEncoding.GZIP,
                size_bytes=len(compressed),
                original_size_bytes=len(content),
                uploaded_at=datetime.now(UTC),
            )

        # Check expiration
        if metadata.expires_at and metadata.expires_at < datetime.now(UTC):
            logger.debug(f"Object expired: {key}")
            return None

        return StorageObject(
            content=content,
            metadata=metadata,
            exists=True,
        )

    def _load_metadata(self, key: str) -> StorageMetadata | None:
        """Load metadata from file."""
        meta_path = self._get_metadata_path(key)
        if not meta_path.exists():
            return None

        try:
            meta_dict = json.loads(meta_path.read_text())
            return StorageMetadata(
                uri=meta_dict["uri"],
                content_hash=meta_dict["content_hash"],
                content_type=ContentType(meta_dict["content_type"]),
                content_encoding=ContentEncoding(meta_dict["content_encoding"]),
                size_bytes=meta_dict["size_bytes"],
                original_size_bytes=meta_dict["original_size_bytes"],
                uploaded_at=datetime.fromisoformat(meta_dict["uploaded_at"]),
                expires_at=datetime.fromisoformat(meta_dict["expires_at"]) if meta_dict.get("expires_at") else None,
                custom_metadata=meta_dict.get("custom_metadata", {}),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load metadata for {key}: {e}")
            return None

    def exists(self, key: str) -> bool:
        """Check if object exists."""
        return self._get_path(key).exists()

    def delete(self, key: str) -> bool:
        """Delete object and metadata."""
        file_path = self._get_path(key)
        meta_path = self._get_metadata_path(key)

        deleted = False
        if file_path.exists():
            file_path.unlink()
            deleted = True
        if meta_path.exists():
            meta_path.unlink()
            deleted = True

        return deleted

    def get_metadata(self, key: str) -> StorageMetadata | None:
        """Get metadata without downloading content."""
        if not self.exists(key):
            return None
        return self._load_metadata(key)

    def list_expired(
        self,
        prefix: str = "raw/",
        older_than_days: int = 90,
    ) -> list:
        """List expired objects."""
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        expired_keys = []

        prefix_path = self._base_path / prefix
        if not prefix_path.exists():
            return []

        for meta_file in prefix_path.rglob(f"*{self._metadata_suffix}"):
            key = str(meta_file.relative_to(self._base_path)).replace(self._metadata_suffix, "")
            metadata = self._load_metadata(key)
            if metadata and metadata.uploaded_at < cutoff:
                expired_keys.append(key)

        return expired_keys

    def list_all(self, prefix: str = "raw/") -> list:
        """List all objects with the given prefix."""
        all_keys = []

        prefix_path = self._base_path / prefix
        if not prefix_path.exists():
            return []

        for meta_file in prefix_path.rglob(f"*{self._metadata_suffix}"):
            key = str(meta_file.relative_to(self._base_path)).replace(self._metadata_suffix, "")
            all_keys.append(key)

        return all_keys

    def delete_all(self, prefix: str = "raw/") -> int:
        """Delete all objects with the given prefix."""
        keys = self.list_all(prefix)
        deleted = 0

        for key in keys:
            if self.delete(key):
                deleted += 1

        return deleted

    def cleanup(self) -> None:
        """Remove all stored content (for testing)."""
        if self._base_path.exists():
            shutil.rmtree(self._base_path)
            self._base_path.mkdir(parents=True, exist_ok=True)
