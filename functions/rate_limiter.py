"""
Rate limiting module for preventing abuse and cost spikes.

This module implements per-user rate limiting using Firestore as the
backing store. It supports configurable limits for different action types.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from firebase_admin import firestore

from utils import get_firestore_client, get_env_int, get_timestamp


class RateLimitType(Enum):
    """Types of rate-limited actions."""
    IMAGE_UPLOAD = "image_upload"
    TEXT_MESSAGE = "text_message"
    REPORT = "report"


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit."""
    limit: int
    window_seconds: int


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    current_count: int
    limit: int
    remaining: int
    reset_at: datetime
    window_seconds: int


# Default rate limit configurations
DEFAULT_RATE_LIMITS = {
    RateLimitType.IMAGE_UPLOAD: RateLimitConfig(
        limit=20,  # 20 images
        window_seconds=3600  # per hour
    ),
    RateLimitType.TEXT_MESSAGE: RateLimitConfig(
        limit=60,  # 60 messages
        window_seconds=60  # per minute
    ),
    RateLimitType.REPORT: RateLimitConfig(
        limit=10,  # 10 reports
        window_seconds=3600  # per hour
    ),
}


def get_rate_limit_config(limit_type: RateLimitType) -> RateLimitConfig:
    """
    Get rate limit configuration, with environment variable overrides.
    
    Args:
        limit_type: Type of rate limit
        
    Returns:
        RateLimitConfig for the given type
    """
    defaults = DEFAULT_RATE_LIMITS[limit_type]
    
    if limit_type == RateLimitType.IMAGE_UPLOAD:
        return RateLimitConfig(
            limit=get_env_int("RATE_LIMIT_IMAGES_PER_HOUR", defaults.limit),
            window_seconds=defaults.window_seconds
        )
    elif limit_type == RateLimitType.TEXT_MESSAGE:
        return RateLimitConfig(
            limit=get_env_int("RATE_LIMIT_TEXTS_PER_MINUTE", defaults.limit),
            window_seconds=defaults.window_seconds
        )
    
    return defaults


def get_window_key(user_id: str, limit_type: RateLimitType, window_seconds: int) -> str:
    """
    Generate a key for the current time window.
    
    Args:
        user_id: User ID
        limit_type: Type of rate limit
        window_seconds: Window size in seconds
        
    Returns:
        Unique key for this user/type/window combination
    """
    now = get_timestamp()
    # Floor to window boundary
    window_start = int(now.timestamp() / window_seconds) * window_seconds
    return f"{user_id}_{limit_type.value}_{window_start}"


def check_rate_limit(
    user_id: str,
    limit_type: RateLimitType,
    increment: bool = True
) -> RateLimitResult:
    """
    Check if a user is within rate limits.
    
    Args:
        user_id: User ID to check
        limit_type: Type of action being rate limited
        increment: Whether to increment the counter (default True)
        
    Returns:
        RateLimitResult with decision and details
    """
    db = get_firestore_client()
    config = get_rate_limit_config(limit_type)
    
    now = get_timestamp()
    window_start_ts = int(now.timestamp() / config.window_seconds) * config.window_seconds
    window_start = datetime.fromtimestamp(window_start_ts, tz=timezone.utc)
    window_end = window_start + timedelta(seconds=config.window_seconds)
    
    # Document key includes user, type, and window
    doc_key = get_window_key(user_id, limit_type, config.window_seconds)
    doc_ref = db.collection("rate_limits").document(doc_key)
    
    @firestore.transactional
    def update_in_transaction(transaction):
        snapshot = doc_ref.get(transaction=transaction)
        
        if snapshot.exists:
            current_count = snapshot.get("count") or 0
        else:
            current_count = 0
        
        # Check if within limit
        allowed = current_count < config.limit
        
        # Increment if allowed and requested
        if allowed and increment:
            new_count = current_count + 1
            transaction.set(doc_ref, {
                "userId": user_id,
                "type": limit_type.value,
                "count": new_count,
                "windowStart": window_start,
                "windowEnd": window_end,
                "lastUpdated": now,
            }, merge=True)
            current_count = new_count
        
        remaining = max(0, config.limit - current_count)
        
        return RateLimitResult(
            allowed=allowed,
            current_count=current_count,
            limit=config.limit,
            remaining=remaining,
            reset_at=window_end,
            window_seconds=config.window_seconds
        )
    
    transaction = db.transaction()
    return update_in_transaction(transaction)


def check_image_upload_limit(user_id: str) -> RateLimitResult:
    """
    Check if user can upload an image.
    
    Args:
        user_id: User ID
        
    Returns:
        RateLimitResult
    """
    return check_rate_limit(user_id, RateLimitType.IMAGE_UPLOAD)


def check_text_message_limit(user_id: str) -> RateLimitResult:
    """
    Check if user can send a text message.
    
    Args:
        user_id: User ID
        
    Returns:
        RateLimitResult
    """
    return check_rate_limit(user_id, RateLimitType.TEXT_MESSAGE)


def check_report_limit(user_id: str) -> RateLimitResult:
    """
    Check if user can submit a report.
    
    Args:
        user_id: User ID
        
    Returns:
        RateLimitResult
    """
    return check_rate_limit(user_id, RateLimitType.REPORT)


def get_user_rate_limit_status(user_id: str) -> dict:
    """
    Get current rate limit status for all limit types.
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with status for each limit type
    """
    status = {}
    
    for limit_type in RateLimitType:
        # Check without incrementing
        result = check_rate_limit(user_id, limit_type, increment=False)
        status[limit_type.value] = {
            "current": result.current_count,
            "limit": result.limit,
            "remaining": result.remaining,
            "resetAt": result.reset_at.isoformat(),
            "windowSeconds": result.window_seconds,
        }
    
    return status


def cleanup_expired_rate_limits(days_old: int = 1) -> int:
    """
    Clean up expired rate limit documents.
    
    This should be called periodically (e.g., daily) to remove
    old rate limit entries.
    
    Args:
        days_old: Remove entries older than this many days
        
    Returns:
        Number of documents deleted
    """
    db = get_firestore_client()
    
    cutoff = get_timestamp() - timedelta(days=days_old)
    
    # Query for old documents
    query = db.collection("rate_limits").where("windowEnd", "<", cutoff)
    docs = query.stream()
    
    deleted = 0
    batch = db.batch()
    batch_size = 0
    
    for doc in docs:
        batch.delete(doc.reference)
        batch_size += 1
        deleted += 1
        
        # Commit in batches of 500
        if batch_size >= 500:
            batch.commit()
            batch = db.batch()
            batch_size = 0
    
    # Commit remaining
    if batch_size > 0:
        batch.commit()
    
    return deleted
