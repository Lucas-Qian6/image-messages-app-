"""
Shared utilities for the content moderation system.
"""

import os
from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum

import firebase_admin
from firebase_admin import credentials, firestore, storage


class ModerationAction(Enum):
    """Possible moderation actions."""
    APPROVED = "approved"
    BLOCKED = "blocked"
    QUEUED = "queued"


class ContentType(Enum):
    """Types of content being moderated."""
    IMAGE = "image"
    TEXT = "text"


class ReportCategory(Enum):
    """Categories for user reports."""
    SPAM = "spam"
    HARASSMENT = "harassment"
    INAPPROPRIATE = "inappropriate"
    OTHER = "other"


class ReportStatus(Enum):
    """Status of a report."""
    PENDING = "pending"
    REVIEWED = "reviewed"


# Initialize Firebase Admin SDK (only once)
_app_initialized = False


def initialize_firebase() -> None:
    """Initialize Firebase Admin SDK if not already initialized."""
    global _app_initialized
    if not _app_initialized:
        try:
            firebase_admin.get_app()
        except ValueError:
            # App not initialized, initialize it
            firebase_admin.initialize_app()
        _app_initialized = True


def get_firestore_client() -> firestore.Client:
    """Get Firestore client instance."""
    initialize_firebase()
    return firestore.client()


def get_storage_bucket(bucket_name: Optional[str] = None) -> storage.bucket:
    """Get Firebase Storage bucket instance."""
    initialize_firebase()
    return storage.bucket(bucket_name)


def get_timestamp() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc)


def get_env_var(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable with optional default."""
    return os.environ.get(name, default)


def get_env_bool(name: str, default: bool = False) -> bool:
    """Get environment variable as boolean."""
    value = os.environ.get(name, str(default)).lower()
    return value in ('true', '1', 'yes')


def get_env_int(name: str, default: int) -> int:
    """Get environment variable as integer."""
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def log_moderation_event(
    user_id: str,
    content_type: ContentType,
    action: ModerationAction,
    reason: str,
    confidence: Optional[dict] = None,
    original_content: Optional[str] = None,
    additional_data: Optional[dict] = None
) -> str:
    """
    Log a moderation event to Firestore.
    
    Args:
        user_id: The ID of the user whose content was moderated
        content_type: Type of content (image or text)
        action: Action taken (approved, blocked, queued)
        reason: Reason for the action
        confidence: Confidence scores (for image moderation)
        original_content: Original content or path
        additional_data: Any additional data to log
        
    Returns:
        The document ID of the created log entry
    """
    db = get_firestore_client()
    
    log_data = {
        "userId": user_id,
        "contentType": content_type.value,
        "action": action.value,
        "reason": reason,
        "timestamp": get_timestamp(),
    }
    
    if confidence:
        log_data["confidence"] = confidence
    
    if original_content:
        log_data["originalContent"] = original_content
    
    if additional_data:
        log_data.update(additional_data)
    
    doc_ref = db.collection("moderation_logs").add(log_data)
    return doc_ref[1].id


def log_blocked_content(
    user_id: str,
    content_type: ContentType,
    original_path: str,
    reason: str
) -> str:
    """
    Log blocked content for potential appeals later.
    
    Args:
        user_id: The ID of the user whose content was blocked
        content_type: Type of content (image or text)
        original_path: Original storage path or content
        reason: Reason for blocking
        
    Returns:
        The document ID of the created entry
    """
    db = get_firestore_client()
    
    doc_data = {
        "userId": user_id,
        "contentType": content_type.value,
        "originalPath": original_path,
        "reason": reason,
        "timestamp": get_timestamp(),
    }
    
    doc_ref = db.collection("blocked_content").add(doc_data)
    return doc_ref[1].id


def increment_user_violations(user_id: str) -> int:
    """
    Increment violation count for a user.
    
    Args:
        user_id: The ID of the user
        
    Returns:
        The new violation count
    """
    db = get_firestore_client()
    doc_ref = db.collection("user_violations").document(user_id)
    
    # Use transaction to safely increment
    @firestore.transactional
    def update_in_transaction(transaction, doc_ref):
        snapshot = doc_ref.get(transaction=transaction)
        if snapshot.exists:
            current_count = snapshot.get("violationCount") or 0
            new_count = current_count + 1
        else:
            new_count = 1
        
        transaction.set(doc_ref, {
            "userId": user_id,
            "violationCount": new_count,
            "lastViolation": get_timestamp(),
        }, merge=True)
        
        return new_count
    
    transaction = db.transaction()
    return update_in_transaction(transaction, doc_ref)


def parse_storage_path(path: str) -> tuple[str, str]:
    """
    Parse a storage path to extract user ID and image ID.
    
    Expected format: /pending/{userId}/{imageId}
    
    Args:
        path: The storage path
        
    Returns:
        Tuple of (user_id, image_id)
    """
    parts = path.strip('/').split('/')
    if len(parts) >= 3:
        return parts[1], parts[2]
    elif len(parts) >= 2:
        return parts[0], parts[1]
    else:
        raise ValueError(f"Invalid storage path format: {path}")
