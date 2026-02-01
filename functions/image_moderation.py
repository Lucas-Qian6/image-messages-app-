"""
Image moderation module using Google Cloud Vision SafeSearch.

This module provides image content moderation by analyzing uploaded images
for adult, violent, racy, medical, and spoof content using Google Cloud
Vision API's SafeSearch detection.
"""

import time
from enum import Enum
from typing import Optional
from dataclasses import dataclass

from google.cloud import vision
from google.api_core import retry
from google.api_core.exceptions import GoogleAPIError

from utils import (
    ModerationAction,
    ContentType,
    get_storage_bucket,
    get_env_var,
    log_moderation_event,
    log_blocked_content,
    increment_user_violations,
)


class SafeSearchLikelihood(Enum):
    """
    SafeSearch likelihood levels from Vision API.
    Values correspond to the API's likelihood enum.
    """
    UNKNOWN = 0
    VERY_UNLIKELY = 1
    UNLIKELY = 2
    POSSIBLE = 3
    LIKELY = 4
    VERY_LIKELY = 5


# Default threshold: block if LIKELY or higher
DEFAULT_THRESHOLD = SafeSearchLikelihood.LIKELY


@dataclass
class ModerationResult:
    """Result of image moderation."""
    allowed: bool
    action: ModerationAction
    reason: str
    scores: dict
    categories_flagged: list[str]


def get_moderation_threshold() -> SafeSearchLikelihood:
    """
    Get the moderation threshold from environment variable.
    
    Returns:
        SafeSearchLikelihood threshold level
    """
    threshold_str = get_env_var("IMAGE_MODERATION_THRESHOLD", "LIKELY")
    try:
        return SafeSearchLikelihood[threshold_str.upper()]
    except KeyError:
        return DEFAULT_THRESHOLD


def likelihood_to_enum(likelihood: int) -> SafeSearchLikelihood:
    """Convert Vision API likelihood int to enum."""
    try:
        return SafeSearchLikelihood(likelihood)
    except ValueError:
        return SafeSearchLikelihood.UNKNOWN


def analyze_image_safesearch(
    image_content: bytes,
    max_retries: int = 3
) -> tuple[dict, Optional[str]]:
    """
    Analyze image content using Google Cloud Vision SafeSearch.
    
    Args:
        image_content: Raw image bytes
        max_retries: Maximum number of retry attempts
        
    Returns:
        Tuple of (scores dict, error message or None)
    """
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=image_content)
    
    # Configure retry with exponential backoff
    retry_config = retry.Retry(
        initial=1.0,  # Initial delay in seconds
        maximum=30.0,  # Maximum delay
        multiplier=2.0,  # Exponential multiplier
        deadline=60.0,  # Total timeout
    )
    
    for attempt in range(max_retries):
        try:
            response = client.safe_search_detection(
                image=image,
                retry=retry_config
            )
            
            if response.error.message:
                return {}, f"Vision API error: {response.error.message}"
            
            safe_search = response.safe_search_annotation
            
            # Convert to dictionary with likelihood values
            scores = {
                "adult": {
                    "likelihood": safe_search.adult,
                    "name": SafeSearchLikelihood(safe_search.adult).name
                },
                "violence": {
                    "likelihood": safe_search.violence,
                    "name": SafeSearchLikelihood(safe_search.violence).name
                },
                "racy": {
                    "likelihood": safe_search.racy,
                    "name": SafeSearchLikelihood(safe_search.racy).name
                },
                "medical": {
                    "likelihood": safe_search.medical,
                    "name": SafeSearchLikelihood(safe_search.medical).name
                },
                "spoof": {
                    "likelihood": safe_search.spoof,
                    "name": SafeSearchLikelihood(safe_search.spoof).name
                },
            }
            
            return scores, None
            
        except GoogleAPIError as e:
            if attempt < max_retries - 1:
                # Exponential backoff
                wait_time = (2 ** attempt) * 1.0
                time.sleep(wait_time)
                continue
            return {}, f"Vision API failed after {max_retries} attempts: {str(e)}"
        except Exception as e:
            return {}, f"Unexpected error during image analysis: {str(e)}"
    
    return {}, "Max retries exceeded"


def evaluate_safesearch_scores(
    scores: dict,
    threshold: SafeSearchLikelihood = None
) -> ModerationResult:
    """
    Evaluate SafeSearch scores against threshold.
    
    Very strict policy: block if any category is at or above threshold.
    Categories checked: adult, violence, racy
    (medical and spoof are informational, not blocked)
    
    Args:
        scores: SafeSearch scores from analyze_image_safesearch
        threshold: Minimum likelihood level to trigger blocking
        
    Returns:
        ModerationResult with decision
    """
    if threshold is None:
        threshold = get_moderation_threshold()
    
    # Categories that trigger blocking
    blocking_categories = ["adult", "violence", "racy"]
    
    flagged_categories = []
    
    for category in blocking_categories:
        if category in scores:
            likelihood = scores[category]["likelihood"]
            if likelihood >= threshold.value:
                flagged_categories.append(category)
    
    if flagged_categories:
        reason = f"Content flagged for: {', '.join(flagged_categories)}"
        return ModerationResult(
            allowed=False,
            action=ModerationAction.BLOCKED,
            reason=reason,
            scores=scores,
            categories_flagged=flagged_categories
        )
    
    return ModerationResult(
        allowed=True,
        action=ModerationAction.APPROVED,
        reason="Content passed moderation",
        scores=scores,
        categories_flagged=[]
    )


def moderate_image(
    image_content: bytes,
    user_id: str,
    image_path: str,
    image_id: str
) -> ModerationResult:
    """
    Full image moderation pipeline.
    
    1. Analyze image with Vision API SafeSearch
    2. Evaluate against threshold
    3. Log the result
    4. Handle violations
    
    Args:
        image_content: Raw image bytes
        user_id: ID of the uploading user
        image_path: Storage path of the image
        image_id: Unique image identifier
        
    Returns:
        ModerationResult with decision and details
    """
    # Analyze the image
    scores, error = analyze_image_safesearch(image_content)
    
    if error:
        # API failure - queue for later
        log_moderation_event(
            user_id=user_id,
            content_type=ContentType.IMAGE,
            action=ModerationAction.QUEUED,
            reason=error,
            original_content=image_path,
            additional_data={"imageId": image_id}
        )
        
        return ModerationResult(
            allowed=False,  # Don't allow until moderated
            action=ModerationAction.QUEUED,
            reason=error,
            scores={},
            categories_flagged=[]
        )
    
    # Evaluate the scores
    result = evaluate_safesearch_scores(scores)
    
    # Log the moderation event
    log_moderation_event(
        user_id=user_id,
        content_type=ContentType.IMAGE,
        action=result.action,
        reason=result.reason,
        confidence=result.scores,
        original_content=image_path,
        additional_data={
            "imageId": image_id,
            "categoriesFlagged": result.categories_flagged
        }
    )
    
    # If blocked, log to blocked content and increment violations
    if not result.allowed and result.action == ModerationAction.BLOCKED:
        log_blocked_content(
            user_id=user_id,
            content_type=ContentType.IMAGE,
            original_path=image_path,
            reason=result.reason
        )
        increment_user_violations(user_id)
    
    return result


def move_image_to_approved(
    source_path: str,
    user_id: str,
    image_id: str,
    bucket_name: Optional[str] = None
) -> str:
    """
    Move an approved image from pending to approved folder.
    
    Args:
        source_path: Current storage path (in pending/)
        user_id: User ID
        image_id: Image ID
        bucket_name: Optional bucket name
        
    Returns:
        New storage path in approved/
    """
    bucket = get_storage_bucket(bucket_name)
    
    source_blob = bucket.blob(source_path.lstrip('/'))
    dest_path = f"approved/{user_id}/{image_id}"
    
    # Copy to new location
    bucket.copy_blob(source_blob, bucket, dest_path)
    
    # Delete from pending
    source_blob.delete()
    
    return dest_path


def move_image_to_queued(
    source_path: str,
    user_id: str,
    image_id: str,
    bucket_name: Optional[str] = None
) -> str:
    """
    Move an image to queued folder for later processing.
    
    Args:
        source_path: Current storage path
        user_id: User ID
        image_id: Image ID
        bucket_name: Optional bucket name
        
    Returns:
        New storage path in queued/
    """
    bucket = get_storage_bucket(bucket_name)
    
    source_blob = bucket.blob(source_path.lstrip('/'))
    dest_path = f"queued/{user_id}/{image_id}"
    
    # Copy to queued location
    bucket.copy_blob(source_blob, bucket, dest_path)
    
    # Delete from pending
    source_blob.delete()
    
    return dest_path


def delete_blocked_image(
    image_path: str,
    bucket_name: Optional[str] = None
) -> bool:
    """
    Delete a blocked image from storage.
    
    Args:
        image_path: Storage path of the image
        bucket_name: Optional bucket name
        
    Returns:
        True if deleted successfully
    """
    try:
        bucket = get_storage_bucket(bucket_name)
        blob = bucket.blob(image_path.lstrip('/'))
        blob.delete()
        return True
    except Exception:
        return False
