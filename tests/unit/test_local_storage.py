"""Tests for LocalStorageProvider path traversal protection."""

import os
import tempfile

import pytest

from app.storage.local_provider import LocalStorageProvider


class TestPathTraversal:
    """Verify _get_path rejects path traversal attempts."""

    def setup_method(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp())
        self.provider = LocalStorageProvider(base_path=self.tmpdir)

    def test_traversal_with_dotdot(self):
        with pytest.raises(ValueError, match="Path traversal detected"):
            self.provider._get_path("../../../etc/passwd")

    def test_traversal_with_absolute(self):
        with pytest.raises(ValueError, match="Path traversal detected"):
            self.provider._get_path("/etc/passwd")

    def test_normal_key_succeeds(self):
        path = self.provider._get_path("articles/abc123.json")
        assert str(path).startswith(self.tmpdir)

    def test_metadata_traversal(self):
        with pytest.raises(ValueError, match="Path traversal detected"):
            self.provider._get_metadata_path("../../../etc/passwd")
