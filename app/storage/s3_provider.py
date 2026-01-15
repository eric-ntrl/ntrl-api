# app/storage/s3_provider.py
"""
S3 storage provider implementation using boto3.

Supports:
- AWS S3
- S3-compatible services (MinIO, DigitalOcean Spaces, etc.)
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.storage.base import (
    StorageProvider,
    StorageObject,
    StorageMetadata,
    ContentType,
    ContentEncoding,
    compute_content_hash,
    compress_content,
    decompress_content,
)

logger = logging.getLogger(__name__)


class S3StorageProvider(StorageProvider):
    """
    S3/S3-compatible storage provider.

    Configuration via environment:
    - S3_BUCKET: Bucket name (required)
    - S3_ENDPOINT_URL: Custom endpoint for S3-compatible services
    - S3_REGION: AWS region (default: us-east-1)
    - AWS_ACCESS_KEY_ID: AWS credentials
    - AWS_SECRET_ACCESS_KEY: AWS credentials
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """
        Initialize S3 provider.

        Args:
            bucket: S3 bucket name (or S3_BUCKET env var)
            endpoint_url: Custom endpoint for S3-compatible services
            region: AWS region
        """
        self._bucket = bucket or os.getenv("S3_BUCKET")
        if not self._bucket:
            raise ValueError("S3 bucket required. Set S3_BUCKET env var or pass bucket.")

        self._endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT_URL")
        self._region = region or os.getenv("S3_REGION", "us-east-1")

        # Configure boto3 client
        config = Config(
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=5,
            read_timeout=30,
        )

        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            config=config,
        )

        logger.info(f"S3 storage initialized: bucket={self._bucket}")

    @property
    def name(self) -> str:
        return "s3"

    @property
    def bucket(self) -> str:
        return self._bucket

    def upload(
        self,
        key: str,
        content: bytes,
        content_type: ContentType = ContentType.TEXT_PLAIN,
        expires_days: Optional[int] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> StorageMetadata:
        """Upload content to S3 with gzip compression."""
        # Compute hash of original content
        content_hash = compute_content_hash(content)
        original_size = len(content)

        # Compress content
        compressed = compress_content(content)
        compressed_size = len(compressed)

        # Prepare S3 metadata
        s3_metadata = metadata or {}
        s3_metadata.update({
            "original-size": str(original_size),
            "content-hash": content_hash,
        })

        # Calculate expiration
        expires_at = None
        extra_args = {
            "ContentType": content_type.value,
            "ContentEncoding": ContentEncoding.GZIP.value,
            "Metadata": s3_metadata,
        }

        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)
            extra_args["Expires"] = expires_at

        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=compressed,
                **extra_args,
            )

            logger.debug(
                f"Uploaded to S3: {key} "
                f"(original={original_size}, compressed={compressed_size})"
            )

            return StorageMetadata(
                uri=key,
                content_hash=content_hash,
                content_type=content_type,
                content_encoding=ContentEncoding.GZIP,
                size_bytes=compressed_size,
                original_size_bytes=original_size,
                uploaded_at=datetime.utcnow(),
                expires_at=expires_at,
                custom_metadata=s3_metadata,
            )

        except ClientError as e:
            logger.error(f"S3 upload failed for {key}: {e}")
            raise

    def download(self, key: str) -> Optional[StorageObject]:
        """Download and decompress content from S3."""
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=key,
            )

            compressed = response["Body"].read()
            s3_metadata = response.get("Metadata", {})

            # Decompress
            content = decompress_content(compressed)

            # Build metadata
            metadata = StorageMetadata(
                uri=key,
                content_hash=s3_metadata.get("content-hash", ""),
                content_type=ContentType(response.get("ContentType", "text/plain")),
                content_encoding=ContentEncoding.GZIP,
                size_bytes=len(compressed),
                original_size_bytes=int(s3_metadata.get("original-size", len(content))),
                uploaded_at=response.get("LastModified", datetime.utcnow()),
                expires_at=response.get("Expires"),
                custom_metadata=s3_metadata,
            )

            return StorageObject(
                content=content,
                metadata=metadata,
                exists=True,
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                logger.debug(f"S3 object not found: {key}")
                return None
            logger.error(f"S3 download failed for {key}: {e}")
            raise

    def exists(self, key: str) -> bool:
        """Check if object exists in S3."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise

    def delete(self, key: str) -> bool:
        """Delete object from S3."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.debug(f"Deleted from S3: {key}")
            return True
        except ClientError as e:
            logger.error(f"S3 delete failed for {key}: {e}")
            return False

    def get_metadata(self, key: str) -> Optional[StorageMetadata]:
        """Get object metadata without downloading content."""
        try:
            response = self._client.head_object(
                Bucket=self._bucket,
                Key=key,
            )

            s3_metadata = response.get("Metadata", {})

            return StorageMetadata(
                uri=key,
                content_hash=s3_metadata.get("content-hash", ""),
                content_type=ContentType(response.get("ContentType", "text/plain")),
                content_encoding=ContentEncoding.GZIP,
                size_bytes=response.get("ContentLength", 0),
                original_size_bytes=int(s3_metadata.get("original-size", 0)),
                uploaded_at=response.get("LastModified", datetime.utcnow()),
                expires_at=response.get("Expires"),
                custom_metadata=s3_metadata,
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return None
            raise

    def list_expired(
        self,
        prefix: str = "raw/",
        older_than_days: int = 90,
    ) -> list:
        """
        List objects older than specified days (for cleanup jobs).

        Returns list of keys that may be candidates for deletion.
        """
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        expired_keys = []

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    if obj["LastModified"].replace(tzinfo=None) < cutoff:
                        expired_keys.append(obj["Key"])
        except ClientError as e:
            logger.error(f"Failed to list expired objects: {e}")

        return expired_keys

    def list_all(self, prefix: str = "raw/") -> list:
        """List all objects with the given prefix."""
        all_keys = []

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    all_keys.append(obj["Key"])
        except ClientError as e:
            logger.error(f"Failed to list objects: {e}")

        return all_keys

    def delete_all(self, prefix: str = "raw/") -> int:
        """Delete all objects with the given prefix."""
        keys = self.list_all(prefix)
        deleted = 0

        # S3 batch delete supports up to 1000 objects at a time
        for i in range(0, len(keys), 1000):
            batch = keys[i:i + 1000]
            try:
                self._client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": k} for k in batch]},
                )
                deleted += len(batch)
            except ClientError as e:
                logger.error(f"Failed to delete batch: {e}")

        return deleted
