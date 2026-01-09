# app/storage/factory.py
"""
Factory function for creating storage providers.
"""

import os
import logging
from typing import Optional

from app.storage.base import StorageProvider

logger = logging.getLogger(__name__)

# Global singleton instance
_storage_provider: Optional[StorageProvider] = None


def get_storage_provider(
    provider_name: Optional[str] = None,
    **kwargs,
) -> StorageProvider:
    """
    Get or create the storage provider instance.

    Args:
        provider_name: 's3' or 'local' (default from STORAGE_PROVIDER env)
        **kwargs: Additional arguments for the provider

    Returns:
        StorageProvider instance (singleton)

    Environment:
        STORAGE_PROVIDER: 's3' (default) or 'local'
    """
    global _storage_provider

    if _storage_provider is not None:
        return _storage_provider

    name = provider_name or os.getenv("STORAGE_PROVIDER", "s3")
    name = name.lower().strip()

    if name == "s3":
        from app.storage.s3_provider import S3StorageProvider
        _storage_provider = S3StorageProvider(**kwargs)
    elif name == "local":
        from app.storage.local_provider import LocalStorageProvider
        _storage_provider = LocalStorageProvider(**kwargs)
    else:
        raise ValueError(f"Unknown storage provider: {name}. Available: s3, local")

    logger.info(f"Storage provider initialized: {_storage_provider.name}")
    return _storage_provider


def set_storage_provider(provider: StorageProvider) -> None:
    """
    Set a custom storage provider (useful for testing).
    """
    global _storage_provider
    _storage_provider = provider


def reset_storage_provider() -> None:
    """
    Reset the storage provider singleton (for testing).
    """
    global _storage_provider
    _storage_provider = None
