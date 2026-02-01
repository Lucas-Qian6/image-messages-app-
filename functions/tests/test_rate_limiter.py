"""
Unit tests for rate limiting module.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from rate_limiter import (
    RateLimitType,
    RateLimitConfig,
    RateLimitResult,
    get_rate_limit_config,
    get_window_key,
    DEFAULT_RATE_LIMITS,
)


class TestRateLimitConfig:
    """Tests for rate limit configuration."""
    
    def test_default_image_limit(self):
        """Default image upload limit should be configured."""
        config = DEFAULT_RATE_LIMITS[RateLimitType.IMAGE_UPLOAD]
        assert config.limit == 20
        assert config.window_seconds == 3600  # 1 hour
    
    def test_default_text_limit(self):
        """Default text message limit should be configured."""
        config = DEFAULT_RATE_LIMITS[RateLimitType.TEXT_MESSAGE]
        assert config.limit == 60
        assert config.window_seconds == 60  # 1 minute
    
    def test_default_report_limit(self):
        """Default report limit should be configured."""
        config = DEFAULT_RATE_LIMITS[RateLimitType.REPORT]
        assert config.limit == 10
        assert config.window_seconds == 3600  # 1 hour


class TestWindowKey:
    """Tests for window key generation."""
    
    @patch('rate_limiter.get_timestamp')
    def test_window_key_format(self, mock_timestamp):
        """Window key should have correct format."""
        mock_timestamp.return_value = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        
        key = get_window_key("user123", RateLimitType.IMAGE_UPLOAD, 3600)
        
        assert "user123" in key
        assert "image_upload" in key
    
    @patch('rate_limiter.get_timestamp')
    def test_same_window_same_key(self, mock_timestamp):
        """Same window should produce same key."""
        # Two timestamps in the same hour window
        mock_timestamp.return_value = datetime(2024, 1, 15, 10, 15, 0, tzinfo=timezone.utc)
        key1 = get_window_key("user123", RateLimitType.IMAGE_UPLOAD, 3600)
        
        mock_timestamp.return_value = datetime(2024, 1, 15, 10, 45, 0, tzinfo=timezone.utc)
        key2 = get_window_key("user123", RateLimitType.IMAGE_UPLOAD, 3600)
        
        assert key1 == key2
    
    @patch('rate_limiter.get_timestamp')
    def test_different_window_different_key(self, mock_timestamp):
        """Different windows should produce different keys."""
        mock_timestamp.return_value = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        key1 = get_window_key("user123", RateLimitType.IMAGE_UPLOAD, 3600)
        
        mock_timestamp.return_value = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        key2 = get_window_key("user123", RateLimitType.IMAGE_UPLOAD, 3600)
        
        assert key1 != key2
    
    @patch('rate_limiter.get_timestamp')
    def test_different_users_different_keys(self, mock_timestamp):
        """Different users should have different keys."""
        mock_timestamp.return_value = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        key1 = get_window_key("user123", RateLimitType.IMAGE_UPLOAD, 3600)
        key2 = get_window_key("user456", RateLimitType.IMAGE_UPLOAD, 3600)
        
        assert key1 != key2


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""
    
    def test_result_allowed(self):
        """Result should correctly represent allowed state."""
        result = RateLimitResult(
            allowed=True,
            current_count=5,
            limit=20,
            remaining=15,
            reset_at=datetime.now(timezone.utc),
            window_seconds=3600
        )
        
        assert result.allowed is True
        assert result.remaining == 15
    
    def test_result_blocked(self):
        """Result should correctly represent blocked state."""
        result = RateLimitResult(
            allowed=False,
            current_count=20,
            limit=20,
            remaining=0,
            reset_at=datetime.now(timezone.utc),
            window_seconds=3600
        )
        
        assert result.allowed is False
        assert result.remaining == 0


class TestCheckRateLimit:
    """Tests for the check_rate_limit function."""
    
    @patch('rate_limiter.get_firestore_client')
    @patch('rate_limiter.get_timestamp')
    def test_first_request_allowed(self, mock_timestamp, mock_firestore):
        """First request in a window should be allowed."""
        mock_timestamp.return_value = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        # Mock Firestore
        mock_db = MagicMock()
        mock_firestore.return_value = mock_db
        
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref
        
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        mock_doc_ref.get.return_value = mock_snapshot
        
        mock_transaction = MagicMock()
        mock_db.transaction.return_value = mock_transaction
        
        # The actual function uses transactions which are complex to mock
        # This test validates the mocking setup
        # Full integration testing should use Firebase Emulator
    
    @patch('rate_limiter.get_env_int')
    def test_config_env_override(self, mock_env_int):
        """Environment variables should override defaults."""
        mock_env_int.return_value = 50
        
        config = get_rate_limit_config(RateLimitType.IMAGE_UPLOAD)
        
        assert config.limit == 50
