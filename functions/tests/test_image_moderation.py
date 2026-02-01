"""
Unit tests for image moderation module.
"""

import pytest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from image_moderation import (
    SafeSearchLikelihood,
    ModerationResult,
    evaluate_safesearch_scores,
    get_moderation_threshold,
)
from utils import ModerationAction


class TestSafeSearchLikelihood:
    """Tests for SafeSearchLikelihood enum."""
    
    def test_likelihood_ordering(self):
        """Likelihood values should be properly ordered."""
        assert SafeSearchLikelihood.UNKNOWN.value < SafeSearchLikelihood.VERY_UNLIKELY.value
        assert SafeSearchLikelihood.VERY_UNLIKELY.value < SafeSearchLikelihood.UNLIKELY.value
        assert SafeSearchLikelihood.UNLIKELY.value < SafeSearchLikelihood.POSSIBLE.value
        assert SafeSearchLikelihood.POSSIBLE.value < SafeSearchLikelihood.LIKELY.value
        assert SafeSearchLikelihood.LIKELY.value < SafeSearchLikelihood.VERY_LIKELY.value


class TestEvaluateSafeSearchScores:
    """Tests for evaluating SafeSearch scores."""
    
    def test_clean_image_approved(self):
        """Image with all low scores should be approved."""
        scores = {
            "adult": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 2, "name": "UNLIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(scores)
        
        assert result.allowed is True
        assert result.action == ModerationAction.APPROVED
        assert result.categories_flagged == []
    
    def test_adult_content_blocked(self):
        """Image with high adult score should be blocked."""
        scores = {
            "adult": {"likelihood": 4, "name": "LIKELY"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(scores)
        
        assert result.allowed is False
        assert result.action == ModerationAction.BLOCKED
        assert "adult" in result.categories_flagged
    
    def test_violence_blocked(self):
        """Image with high violence score should be blocked."""
        scores = {
            "adult": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "violence": {"likelihood": 5, "name": "VERY_LIKELY"},
            "racy": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(scores)
        
        assert result.allowed is False
        assert "violence" in result.categories_flagged
    
    def test_racy_blocked(self):
        """Image with high racy score should be blocked."""
        scores = {
            "adult": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 4, "name": "LIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(scores)
        
        assert result.allowed is False
        assert "racy" in result.categories_flagged
    
    def test_medical_not_blocked(self):
        """Medical content alone should not block."""
        scores = {
            "adult": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "medical": {"likelihood": 5, "name": "VERY_LIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(scores)
        
        # Medical is not in blocking categories
        assert result.allowed is True
    
    def test_spoof_not_blocked(self):
        """Spoof content alone should not block."""
        scores = {
            "adult": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 5, "name": "VERY_LIKELY"},
        }
        
        result = evaluate_safesearch_scores(scores)
        
        assert result.allowed is True
    
    def test_multiple_violations(self):
        """Multiple violations should all be flagged."""
        scores = {
            "adult": {"likelihood": 5, "name": "VERY_LIKELY"},
            "violence": {"likelihood": 4, "name": "LIKELY"},
            "racy": {"likelihood": 5, "name": "VERY_LIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(scores)
        
        assert result.allowed is False
        assert len(result.categories_flagged) == 3
        assert "adult" in result.categories_flagged
        assert "violence" in result.categories_flagged
        assert "racy" in result.categories_flagged
    
    def test_possible_not_blocked_by_default(self):
        """POSSIBLE likelihood should not block with default LIKELY threshold."""
        scores = {
            "adult": {"likelihood": 3, "name": "POSSIBLE"},
            "violence": {"likelihood": 3, "name": "POSSIBLE"},
            "racy": {"likelihood": 3, "name": "POSSIBLE"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(
            scores, 
            threshold=SafeSearchLikelihood.LIKELY
        )
        
        assert result.allowed is True
    
    def test_custom_threshold_possible(self):
        """Custom POSSIBLE threshold should block POSSIBLE content."""
        scores = {
            "adult": {"likelihood": 3, "name": "POSSIBLE"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }
        
        result = evaluate_safesearch_scores(
            scores, 
            threshold=SafeSearchLikelihood.POSSIBLE
        )
        
        assert result.allowed is False
        assert "adult" in result.categories_flagged


class TestModerateImage:
    """Tests for the full moderation pipeline."""
    
    @patch('image_moderation.analyze_image_safesearch')
    @patch('image_moderation.log_moderation_event')
    def test_moderate_clean_image(self, mock_log, mock_analyze):
        """Clean image should be approved."""
        mock_analyze.return_value = ({
            "adult": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }, None)
        
        from image_moderation import moderate_image
        
        result = moderate_image(
            image_content=b"fake image bytes",
            user_id="user123",
            image_path="/pending/user123/image1.jpg",
            image_id="image1"
        )
        
        assert result.allowed is True
        assert result.action == ModerationAction.APPROVED
    
    @patch('image_moderation.analyze_image_safesearch')
    @patch('image_moderation.log_moderation_event')
    @patch('image_moderation.log_blocked_content')
    @patch('image_moderation.increment_user_violations')
    def test_moderate_blocked_image(self, mock_increment, mock_log_blocked, mock_log, mock_analyze):
        """Inappropriate image should be blocked."""
        mock_analyze.return_value = ({
            "adult": {"likelihood": 5, "name": "VERY_LIKELY"},
            "violence": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "racy": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "medical": {"likelihood": 1, "name": "VERY_UNLIKELY"},
            "spoof": {"likelihood": 1, "name": "VERY_UNLIKELY"},
        }, None)
        
        from image_moderation import moderate_image
        
        result = moderate_image(
            image_content=b"fake image bytes",
            user_id="user123",
            image_path="/pending/user123/image1.jpg",
            image_id="image1"
        )
        
        assert result.allowed is False
        assert result.action == ModerationAction.BLOCKED
        mock_log_blocked.assert_called_once()
        mock_increment.assert_called_once()
    
    @patch('image_moderation.analyze_image_safesearch')
    @patch('image_moderation.log_moderation_event')
    def test_moderate_api_failure(self, mock_log, mock_analyze):
        """API failure should queue the image."""
        mock_analyze.return_value = ({}, "Vision API error")
        
        from image_moderation import moderate_image
        
        result = moderate_image(
            image_content=b"fake image bytes",
            user_id="user123",
            image_path="/pending/user123/image1.jpg",
            image_id="image1"
        )
        
        assert result.allowed is False
        assert result.action == ModerationAction.QUEUED
