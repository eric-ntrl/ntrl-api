# tests/conftest.py
"""
Pytest configuration and fixtures.
"""

import os
import pytest

# Set test environment
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
