"""
User reporting module for content reports.

This module handles user-submitted reports for inappropriate content,
allowing users to report messages/images with predefined categories
and optional descriptions.
"""

from typing import Optional
from dataclasses import dataclass

from utils import (
    get_firestore_client,
    get_timestamp,
    ReportCategory,
    ReportStatus,
)
from rate_limiter import check_report_limit


@dataclass
class ReportResult:
    """Result of submitting a report."""
    success: bool
    report_id: Optional[str]
    error: Optional[str]


def validate_report_category(category: str) -> bool:
    """
    Validate that a category string is valid.
    
    Args:
        category: Category string to validate
        
    Returns:
        True if valid
    """
    valid_categories = [c.value for c in ReportCategory]
    return category.lower() in valid_categories


def submit_report(
    reporter_id: str,
    message_id: str,
    category: str,
    description: Optional[str] = None
) -> ReportResult:
    """
    Submit a user report.
    
    Args:
        reporter_id: ID of the user submitting the report
        message_id: ID of the message/content being reported
        category: Category of the report (spam, harassment, inappropriate, other)
        description: Optional free-text description
        
    Returns:
        ReportResult with success status
    """
    # Validate category
    if not validate_report_category(category):
        return ReportResult(
            success=False,
            report_id=None,
            error=f"Invalid category: {category}. Must be one of: spam, harassment, inappropriate, other"
        )
    
    # Check rate limit
    rate_limit = check_report_limit(reporter_id)
    if not rate_limit.allowed:
        return ReportResult(
            success=False,
            report_id=None,
            error=f"Rate limit exceeded. You can submit {rate_limit.limit} reports per hour. "
                  f"Try again at {rate_limit.reset_at.isoformat()}"
        )
    
    # Validate description length
    if description and len(description) > 1000:
        return ReportResult(
            success=False,
            report_id=None,
            error="Description too long. Maximum 1000 characters."
        )
    
    # Create report document
    db = get_firestore_client()
    
    report_data = {
        "reporterId": reporter_id,
        "messageId": message_id,
        "category": category.lower(),
        "status": ReportStatus.PENDING.value,
        "timestamp": get_timestamp(),
    }
    
    if description:
        report_data["description"] = description.strip()
    
    # Add to Firestore
    doc_ref = db.collection("reports").add(report_data)
    report_id = doc_ref[1].id
    
    return ReportResult(
        success=True,
        report_id=report_id,
        error=None
    )


def get_pending_reports(limit: int = 50) -> list[dict]:
    """
    Get pending reports for admin review.
    
    Args:
        limit: Maximum number of reports to return
        
    Returns:
        List of pending report documents
    """
    db = get_firestore_client()
    
    query = (
        db.collection("reports")
        .where("status", "==", ReportStatus.PENDING.value)
        .order_by("timestamp")
        .limit(limit)
    )
    
    docs = query.stream()
    
    reports = []
    for doc in docs:
        report = doc.to_dict()
        report["id"] = doc.id
        reports.append(report)
    
    return reports


def get_reports_by_message(message_id: str) -> list[dict]:
    """
    Get all reports for a specific message.
    
    Args:
        message_id: ID of the message
        
    Returns:
        List of reports for this message
    """
    db = get_firestore_client()
    
    query = (
        db.collection("reports")
        .where("messageId", "==", message_id)
        .order_by("timestamp", direction="DESCENDING")
    )
    
    docs = query.stream()
    
    reports = []
    for doc in docs:
        report = doc.to_dict()
        report["id"] = doc.id
        reports.append(report)
    
    return reports


def get_reports_by_user(reporter_id: str, limit: int = 20) -> list[dict]:
    """
    Get reports submitted by a specific user.
    
    Args:
        reporter_id: ID of the reporting user
        limit: Maximum number of reports to return
        
    Returns:
        List of reports by this user
    """
    db = get_firestore_client()
    
    query = (
        db.collection("reports")
        .where("reporterId", "==", reporter_id)
        .order_by("timestamp", direction="DESCENDING")
        .limit(limit)
    )
    
    docs = query.stream()
    
    reports = []
    for doc in docs:
        report = doc.to_dict()
        report["id"] = doc.id
        reports.append(report)
    
    return reports


def mark_report_reviewed(report_id: str, reviewer_notes: Optional[str] = None) -> bool:
    """
    Mark a report as reviewed.
    
    Args:
        report_id: ID of the report
        reviewer_notes: Optional notes from the reviewer
        
    Returns:
        True if successful
    """
    db = get_firestore_client()
    
    doc_ref = db.collection("reports").document(report_id)
    
    update_data = {
        "status": ReportStatus.REVIEWED.value,
        "reviewedAt": get_timestamp(),
    }
    
    if reviewer_notes:
        update_data["reviewerNotes"] = reviewer_notes
    
    try:
        doc_ref.update(update_data)
        return True
    except Exception:
        return False


def get_report_stats() -> dict:
    """
    Get report statistics for monitoring.
    
    Returns:
        Dictionary with report statistics
    """
    db = get_firestore_client()
    
    # Count pending reports
    pending_query = (
        db.collection("reports")
        .where("status", "==", ReportStatus.PENDING.value)
    )
    pending_count = len(list(pending_query.stream()))
    
    # Count by category (for pending only)
    stats_by_category = {}
    for category in ReportCategory:
        cat_query = (
            db.collection("reports")
            .where("status", "==", ReportStatus.PENDING.value)
            .where("category", "==", category.value)
        )
        stats_by_category[category.value] = len(list(cat_query.stream()))
    
    return {
        "pendingCount": pending_count,
        "byCategory": stats_by_category,
    }
