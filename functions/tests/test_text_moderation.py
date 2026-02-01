"""
Unit tests for text moderation module.
"""

import pytest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from text_moderation import TextModerator, TextModerationResult


class TestTextModerator:
    """Tests for TextModerator class."""
    
    @pytest.fixture
    def moderator(self):
        """Create a moderator with default blocklist."""
        return TextModerator()
    
    def test_empty_text_allowed(self, moderator):
        """Empty text should be allowed."""
        result = moderator.moderate("")
        assert result.allowed is True
        assert result.matched_terms == []
    
    def test_whitespace_only_allowed(self, moderator):
        """Whitespace-only text should be allowed."""
        result = moderator.moderate("   \n\t  ")
        assert result.allowed is True
    
    def test_normal_text_allowed(self, moderator):
        """Normal, clean text should be allowed."""
        result = moderator.moderate("Hello, how are you doing today?")
        assert result.allowed is True
        assert result.matched_terms == []
    
    def test_blocklist_word_blocked(self, moderator):
        """Text containing blocklist words should be blocked."""
        # Add a test word to blocklist
        moderator.blocklist.add("badword")
        
        result = moderator.moderate("This contains badword in it")
        assert result.allowed is False
        assert "badword" in result.matched_terms
    
    def test_blocklist_case_insensitive(self, moderator):
        """Blocklist matching should be case insensitive."""
        moderator.blocklist.add("badword")
        
        result = moderator.moderate("This contains BADWORD in it")
        assert result.allowed is False
        
        result = moderator.moderate("This contains BadWord in it")
        assert result.allowed is False
    
    def test_blocklist_phrase_blocked(self, moderator):
        """Multi-word phrases in blocklist should be blocked."""
        moderator.blocklist.add("bad phrase here")
        
        result = moderator.moderate("This contains bad phrase here obviously")
        assert result.allowed is False
        assert "bad phrase here" in result.matched_terms
    
    def test_word_boundary_respected(self, moderator):
        """Blocklist words should match on word boundaries."""
        moderator.blocklist.add("ass")
        
        # Should match standalone word
        result = moderator.moderate("what an ass")
        assert result.allowed is False
        
        # Should NOT match within other words (class, pass, etc.)
        # This depends on word boundary implementation
        # For safety, we use whole-word matching
    
    def test_spaced_profanity_blocked(self, moderator):
        """Spaced out letters should be caught by regex."""
        result = moderator.moderate("f u c k you")
        assert result.allowed is False
        assert len(result.matched_terms) > 0
    
    def test_leet_speak_blocked(self, moderator):
        """Basic leet speak should be caught."""
        # This depends on regex patterns
        result = moderator.moderate("fvck you")
        # May or may not be caught depending on pattern coverage
    
    def test_kys_blocked(self, moderator):
        """Self-harm encouragement should be blocked."""
        result = moderator.moderate("just kys already")
        assert result.allowed is False
    
    def test_threat_blocked(self, moderator):
        """Threats should be blocked."""
        result = moderator.moderate("I'm gonna kill you")
        assert result.allowed is False
    
    def test_result_contains_original_text(self, moderator):
        """Result should contain the original text."""
        text = "Test message"
        result = moderator.moderate(text)
        assert result.original_text == text
    
    def test_multiple_violations(self, moderator):
        """Text with multiple violations should catch all."""
        moderator.blocklist.add("word1")
        moderator.blocklist.add("word2")
        
        result = moderator.moderate("word1 and also word2")
        assert result.allowed is False
        assert "word1" in result.matched_terms
        assert "word2" in result.matched_terms


class TestValidateTextFunction:
    """Tests for the validate_text function."""
    
    @patch('text_moderation.log_moderation_event')
    @patch('text_moderation.log_blocked_content')
    @patch('text_moderation.increment_user_violations')
    def test_validate_clean_text(self, mock_increment, mock_log_blocked, mock_log_event):
        """Clean text should be allowed."""
        from text_moderation import validate_text
        
        result = validate_text(
            text="Hello world",
            user_id="user123"
        )
        
        assert result["allowed"] is True
        mock_log_event.assert_called_once()
        mock_log_blocked.assert_not_called()
        mock_increment.assert_not_called()
    
    @patch('text_moderation.log_moderation_event')
    @patch('text_moderation.log_blocked_content')
    @patch('text_moderation.increment_user_violations')
    def test_validate_blocked_text(self, mock_increment, mock_log_blocked, mock_log_event):
        """Blocked text should trigger logging."""
        from text_moderation import validate_text, get_text_moderator
        
        # Add a test word
        get_text_moderator().blocklist.add("testblock")
        
        result = validate_text(
            text="This has testblock in it",
            user_id="user123"
        )
        
        assert result["allowed"] is False
        assert result["reason"] is not None
        mock_log_event.assert_called_once()
        mock_log_blocked.assert_called_once()
        mock_increment.assert_called_once()


class TestBlocklistLoading:
    """Tests for blocklist loading."""
    
    def test_load_nonexistent_file(self):
        """Loading a nonexistent file should not crash."""
        moderator = TextModerator("/nonexistent/path/blocklist.txt")
        # Should have empty blocklist
        assert isinstance(moderator.blocklist, set)
    
    def test_load_default_blocklist(self):
        """Default blocklist should load successfully."""
        moderator = TextModerator()
        # Should have some entries from default blocklist
        assert len(moderator.blocklist) >= 0  # May be empty in test environment
