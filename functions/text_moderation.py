"""
Text moderation module using keyword filtering and regex patterns.

This module provides text content moderation by checking messages against
a blocklist of inappropriate words/phrases and regex patterns for common
evasion attempts.
"""

import re
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from utils import (
    ModerationAction,
    ContentType,
    log_moderation_event,
    log_blocked_content,
    increment_user_violations,
    get_env_bool,
)


@dataclass
class TextModerationResult:
    """Result of text moderation."""
    allowed: bool
    reason: Optional[str]
    matched_terms: list[str]
    original_text: str


class TextModerator:
    """
    Text content moderator using keyword filtering and regex patterns.
    
    Features:
    - Keyword/phrase blocklist matching
    - Case-insensitive matching
    - Basic regex patterns for evasion detection
    - Configurable blocklist from file
    """
    
    def __init__(self, blocklist_path: Optional[str] = None):
        """
        Initialize the text moderator.
        
        Args:
            blocklist_path: Path to blocklist file. If None, uses default.
        """
        self.blocklist: set[str] = set()
        self.regex_patterns: list[tuple[re.Pattern, str]] = []
        
        # Load blocklist
        if blocklist_path is None:
            # Default to blocklist.txt in same directory
            blocklist_path = Path(__file__).parent / "blocklist.txt"
        
        self._load_blocklist(blocklist_path)
        self._compile_regex_patterns()
    
    def _load_blocklist(self, path: str | Path) -> None:
        """
        Load blocklist from file.
        
        Args:
            path: Path to blocklist file
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        # Store lowercase for case-insensitive matching
                        self.blocklist.add(line.lower())
        except FileNotFoundError:
            # If file not found, start with empty blocklist
            pass
    
    def _compile_regex_patterns(self) -> None:
        """
        Compile regex patterns for common evasion attempts.
        
        This covers basic substitutions. More sophisticated evasion
        detection can be added later based on observed abuse patterns.
        """
        # Pattern: Letters separated by spaces/punctuation (e.g., "f u c k")
        # This is a basic pattern - can be expanded
        self.regex_patterns = [
            # Spaced out letters (e.g., "f u c k", "s.h.i.t")
            (re.compile(r'[fF]\s*[uU]\s*[cC]\s*[kK]', re.IGNORECASE), "profanity"),
            (re.compile(r'[sS]\s*[hH]\s*[iI]\s*[tT]', re.IGNORECASE), "profanity"),
            (re.compile(r'[aA]\s*[sS]\s*[sS]\s*[hH]\s*[oO]\s*[lL]\s*[eE]', re.IGNORECASE), "profanity"),
            
            # Common leet speak substitutions
            (re.compile(r'[fF][uU@][cC][kK]', re.IGNORECASE), "profanity"),
            (re.compile(r'[sS][hH][iI1!][tT]', re.IGNORECASE), "profanity"),
            (re.compile(r'[aA@][sS\$][sS\$]', re.IGNORECASE), "profanity"),
            
            # Hate speech patterns (add more as needed)
            (re.compile(r'k+\s*y+\s*s+', re.IGNORECASE), "self-harm encouragement"),
            
            # Threat patterns
            (re.compile(r'(i\'?ll?|ima?|going to|gonna)\s+(kill|murder|hurt)\s+(you|u)', re.IGNORECASE), "threat"),
        ]
    
    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for matching.
        
        Args:
            text: Original text
            
        Returns:
            Normalized lowercase text
        """
        return text.lower()
    
    def _check_blocklist(self, text: str) -> list[str]:
        """
        Check text against blocklist.
        
        Args:
            text: Text to check (already normalized)
            
        Returns:
            List of matched terms
        """
        matched = []
        
        for term in self.blocklist:
            # Check for whole word match or phrase match
            # Use word boundaries for single words
            if ' ' in term:
                # Phrase - check for substring
                if term in text:
                    matched.append(term)
            else:
                # Single word - use word boundary regex
                pattern = r'\b' + re.escape(term) + r'\b'
                if re.search(pattern, text, re.IGNORECASE):
                    matched.append(term)
        
        return matched
    
    def _check_regex_patterns(self, text: str) -> list[str]:
        """
        Check text against regex patterns.
        
        Args:
            text: Original text
            
        Returns:
            List of matched pattern descriptions
        """
        matched = []
        
        for pattern, description in self.regex_patterns:
            if pattern.search(text):
                matched.append(f"regex:{description}")
        
        return matched
    
    def moderate(self, text: str) -> TextModerationResult:
        """
        Moderate text content.
        
        Args:
            text: Text to moderate
            
        Returns:
            TextModerationResult with decision
        """
        if not text or not text.strip():
            return TextModerationResult(
                allowed=True,
                reason=None,
                matched_terms=[],
                original_text=text
            )
        
        normalized = self._normalize_text(text)
        matched_terms = []
        
        # Check blocklist
        blocklist_matches = self._check_blocklist(normalized)
        matched_terms.extend(blocklist_matches)
        
        # Check regex patterns
        regex_matches = self._check_regex_patterns(text)
        matched_terms.extend(regex_matches)
        
        if matched_terms:
            return TextModerationResult(
                allowed=False,
                reason=f"Content contains prohibited terms: {', '.join(matched_terms[:3])}{'...' if len(matched_terms) > 3 else ''}",
                matched_terms=matched_terms,
                original_text=text
            )
        
        return TextModerationResult(
            allowed=True,
            reason=None,
            matched_terms=[],
            original_text=text
        )


# Global moderator instance (lazy loaded)
_moderator: Optional[TextModerator] = None


def get_text_moderator() -> TextModerator:
    """Get or create the global text moderator instance."""
    global _moderator
    if _moderator is None:
        _moderator = TextModerator()
    return _moderator


def validate_text(
    text: str,
    user_id: str,
    context: Optional[str] = None
) -> dict:
    """
    Validate text content for moderation.
    
    This is the main entry point for text moderation, designed to be
    called from a Cloud Function.
    
    Args:
        text: Text content to validate
        user_id: ID of the user sending the message
        context: Optional context (e.g., conversation ID)
        
    Returns:
        Dictionary with:
        - allowed: bool
        - reason: Optional[str] (if blocked)
    """
    moderator = get_text_moderator()
    result = moderator.moderate(text)
    
    # Log the moderation event
    action = ModerationAction.APPROVED if result.allowed else ModerationAction.BLOCKED
    
    log_moderation_event(
        user_id=user_id,
        content_type=ContentType.TEXT,
        action=action,
        reason=result.reason or "Content passed moderation",
        original_content=text if get_env_bool("VERBOSE_LOGGING", True) else None,
        additional_data={
            "context": context,
            "matchedTerms": result.matched_terms if not result.allowed else []
        }
    )
    
    # If blocked, log to blocked content and increment violations
    if not result.allowed:
        log_blocked_content(
            user_id=user_id,
            content_type=ContentType.TEXT,
            original_path=text,  # For text, store the content itself
            reason=result.reason
        )
        increment_user_violations(user_id)
    
    return {
        "allowed": result.allowed,
        "reason": result.reason
    }


def reload_blocklist(path: Optional[str] = None) -> None:
    """
    Reload the blocklist (useful for hot updates).
    
    Args:
        path: Optional new path to blocklist file
    """
    global _moderator
    _moderator = TextModerator(path)
