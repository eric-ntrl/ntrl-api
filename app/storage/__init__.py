# app/storage/__init__.py
"""
Storage provider abstraction for raw article content.

Raw article bodies are stored in object storage (S3), not Postgres.
This module provides a clean interface for upload/download operations.
"""

from app.storage.base import (
    ContentEncoding,
    ContentType,
    StorageMetadata,
    StorageObject,
    StorageProvider,
)
from app.storage.factory import (
    get_storage_provider,
    reset_storage_provider,
    set_storage_provider,
)
from app.storage.local_provider import LocalStorageProvider
from app.storage.s3_provider import S3StorageProvider

__all__ = [
    "StorageProvider",
    "StorageObject",
    "StorageMetadata",
    "ContentType",
    "ContentEncoding",
    "S3StorageProvider",
    "LocalStorageProvider",
    "get_storage_provider",
    "set_storage_provider",
    "reset_storage_provider",
]
