"""
Unit tests for reporting module.
"""

import pytest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from reporting import (
    validate_report_category,
    submit_report,
    ReportResult,
)
from utils import ReportCategory


class TestValidateReportCategory:
    """Tests for category validation."""
    
    def test_valid_categories(self):
        """Valid categories should pass validation."""
        assert validate_report_category("spam") is True
        assert validate_report_category("harassment") is True
        assert validate_report_category("inappropriate") is True
        assert validate_report_category("other") is True
    
    def test_case_insensitive(self):
        """Category validation should be case insensitive."""
        assert validate_report_category("SPAM") is True
        assert validate_report_category("Harassment") is True
        assert validate_report_category("INAPPROPRIATE") is True
    
    def test_invalid_categories(self):
        """Invalid categories should fail validation."""
        assert validate_report_category("invalid") is False
        assert validate_report_category("") is False
        assert validate_report_category("violence") is False  # Not in our list


class TestSubmitReport:
    """Tests for report submission."""
    
    @patch('reporting.check_report_limit')
    @patch('reporting.get_firestore_client')
    def test_submit_valid_report(self, mock_firestore, mock_rate_limit):
        """Valid report should be submitted successfully."""
        # Mock rate limit - allowed
        mock_rate_limit.return_value = MagicMock(allowed=True)
        
        # Mock Firestore
        mock_db = MagicMock()
        mock_firestore.return_value = mock_db
        
        mock_doc = MagicMock()
        mock_doc.id = "report123"
        mock_db.collection.return_value.add.return_value = (None, mock_doc)
        
        result = submit_report(
            reporter_id="user123",
            message_id="msg456",
            category="spam",
            description="This is spam"
        )
        
        assert result.success is True
        assert result.report_id == "report123"
        assert result.error is None
    
    def test_invalid_category_rejected(self):
        """Invalid category should be rejected."""
        result = submit_report(
            reporter_id="user123",
            message_id="msg456",
            category="invalid_category"
        )
        
        assert result.success is False
        assert "Invalid category" in result.error
    
    @patch('reporting.check_report_limit')
    def test_rate_limit_exceeded(self, mock_rate_limit):
        """Rate limited user should be rejected."""
        from datetime import datetime, timezone
        
        mock_rate_limit.return_value = MagicMock(
            allowed=False,
            limit=10,
            reset_at=datetime.now(timezone.utc)
        )
        
        result = submit_report(
            reporter_id="user123",
            message_id="msg456",
            category="spam"
        )
        
        assert result.success is False
        assert "Rate limit" in result.error
    
    @patch('reporting.check_report_limit')
    def test_description_too_long(self, mock_rate_limit):
        """Too long description should be rejected."""
        mock_rate_limit.return_value = MagicMock(allowed=True)
        
        long_description = "x" * 1001
        
        result = submit_report(
            reporter_id="user123",
            message_id="msg456",
            category="spam",
            description=long_description
        )
        
        assert result.success is False
        assert "too long" in result.error.lower()
    
    @patch('reporting.check_report_limit')
    @patch('reporting.get_firestore_client')
    def test_optional_description(self, mock_firestore, mock_rate_limit):
        """Report without description should succeed."""
        mock_rate_limit.return_value = MagicMock(allowed=True)
        
        mock_db = MagicMock()
        mock_firestore.return_value = mock_db
        
        mock_doc = MagicMock()
        mock_doc.id = "report123"
        mock_db.collection.return_value.add.return_value = (None, mock_doc)
        
        result = submit_report(
            reporter_id="user123",
            message_id="msg456",
            category="harassment"
            # No description
        )
        
        assert result.success is True


class TestReportCategories:
    """Tests for report category enum."""
    
    def test_all_categories_defined(self):
        """All expected categories should be defined."""
        categories = [c.value for c in ReportCategory]
        
        assert "spam" in categories
        assert "harassment" in categories
        assert "inappropriate" in categories
        assert "other" in categories
