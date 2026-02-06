"""
Firebase Cloud Functions entry point for Content Moderation System.

This module defines all Cloud Functions for image and text moderation,
user reporting, and administrative operations.

Functions:
- on_image_upload: Storage trigger for image moderation
- validate_text: HTTPS callable for text moderation
- submit_report: HTTPS callable for user reports
- process_queued_images: Scheduled function for failed moderation retries
- cleanup_rate_limits: Scheduled function for rate limit cleanup
"""

import json
from firebase_functions import https_fn, storage_fn, scheduler_fn, options
from firebase_admin import auth

from utils import (
    get_env_var, 
    initialize_firebase,
    parse_storage_path,
    get_storage_bucket,
    get_env_bool,
    ModerationAction,
)
from image_moderation import (
    moderate_image,
    move_image_to_approved,
    move_image_to_queued,
    delete_blocked_image,
)
from image_processing import (
    process_approved_image,
    upload_processed_images,
)
from text_moderation import validate_text as validate_text_content
from rate_limiter import (
    check_image_upload_limit,
    check_text_message_limit,
    cleanup_expired_rate_limits,
    get_user_rate_limit_status,
)
from reporting import (
    submit_report as submit_user_report,
    get_report_stats,
)


# Initialize Firebase on cold start
initialize_firebase()


# ============================================================================
# IMAGE MODERATION
# ============================================================================

@storage_fn.on_object_finalized(
    region="US-CENTRAL1",
    bucket = "amialone-ba57a.firebasestorage.app",
    memory=options.MemoryOption.MB_512,
    timeout_sec=120,
)
def on_image_upload(event: storage_fn.CloudEvent[storage_fn.StorageObjectData]):
    """
    Triggered when an image is uploaded to the pending folder.
    
    Flow:
    1. Check rate limit
    2. Download image
    3. Run SafeSearch moderation
    4. If approved: process image and move to approved folder
    5. If blocked: delete and log
    6. If API fails: queue for later
    """
    file_path = event.data.name
    bucket_name = event.data.bucket
    content_type = event.data.content_type
    
    # Only process images in pending folder
    if not file_path.startswith("pending/"):
        return
    
    # Verify it's an image
    if not content_type or not content_type.startswith("image/"):
        print(f"Skipping non-image file: {file_path}")
        return
    
    # Parse user_id and image_id from path
    try:
        user_id, image_id = parse_storage_path(file_path)
    except ValueError as e:
        print(f"Error parsing storage path: {e}")
        return
    
    # Check rate limit
    rate_limit = check_image_upload_limit(user_id)
    if not rate_limit.allowed:
        print(f"Rate limit exceeded for user {user_id}")
        # Delete the image
        delete_blocked_image(file_path, bucket_name)
        return
    
    # Download the image
    bucket = get_storage_bucket(bucket_name)
    blob = bucket.blob(file_path)
    
    try:
        image_content = blob.download_as_bytes()
    except Exception as e:
        print(f"Error downloading image: {e}")
        return
    
    # Run moderation
    result = moderate_image(
        image_content=image_content,
        user_id=user_id,
        image_path=file_path,
        image_id=image_id
    )
    
    if result.action == ModerationAction.APPROVED:
        # Process image (compress + thumbnail)
        try:
            processed = process_approved_image(image_content)
            
            # Upload processed versions
            paths = upload_processed_images(
                processed=processed,
                user_id=user_id,
                image_id=image_id,
                bucket_name=bucket_name
            )
            
            # Delete from pending
            blob.delete()
            
            print(f"Image approved and processed: {paths}")
            
        except Exception as e:
            print(f"Error processing approved image: {e}")
            # Move to approved anyway (without processing)
            try:
                move_image_to_approved(file_path, user_id, image_id, bucket_name)
            except Exception as move_error:
                print(f"Error moving to approved: {move_error}")
    
    elif result.action == ModerationAction.BLOCKED:
        # Delete the blocked image
        delete_blocked_image(file_path, bucket_name)
        print(f"Image blocked and deleted: {result.reason}")
    
    elif result.action == ModerationAction.QUEUED:
        # Move to queued for later processing
        try:
            move_image_to_queued(file_path, user_id, image_id, bucket_name)
            print(f"Image queued for later: {result.reason}")
        except Exception as e:
            print(f"Error moving to queue: {e}")


# ============================================================================
# TEXT MODERATION
# ============================================================================

@https_fn.on_call(
    memory=options.MemoryOption.MB_256,
    timeout_sec=30,
)
def validate_text(req: https_fn.CallableRequest) -> dict:
    """
    HTTPS callable function to validate text content.
    
    Request data:
        - text: string - The text to validate
        - context: string (optional) - Context like conversation ID
    
    Response:
        - allowed: boolean
        - reason: string (if blocked)
    """
    # Verify authentication
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required"
        )
    
    user_id = req.auth.uid
    
    # Get request data
    data = req.data or {}
    text = data.get("text", "")
    context = data.get("context")
    
    if not text:
        return {"allowed": True, "reason": None}
    
    # Check rate limit
    rate_limit = check_text_message_limit(user_id)
    if not rate_limit.allowed:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.RESOURCE_EXHAUSTED,
            message=f"Rate limit exceeded. Try again at {rate_limit.reset_at.isoformat()}"
        )
    
    # Validate text
    result = validate_text_content(
        text=text,
        user_id=user_id,
        context=context
    )
    
    return result


# ============================================================================
# USER REPORTING
# ============================================================================

@https_fn.on_call(
    memory=options.MemoryOption.MB_256,
    timeout_sec=30,
)
def submit_report(req: https_fn.CallableRequest) -> dict:
    """
    HTTPS callable function to submit a user report.
    
    Request data:
        - messageId: string - ID of the message being reported
        - category: string - One of: spam, harassment, inappropriate, other
        - description: string (optional) - Additional details
    
    Response:
        - success: boolean
        - reportId: string (if successful)
        - error: string (if failed)
    """
    # Verify authentication
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required"
        )
    
    user_id = req.auth.uid
    
    # Get request data
    data = req.data or {}
    message_id = data.get("messageId")
    category = data.get("category")
    description = data.get("description")
    
    # Validate required fields
    if not message_id:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message="messageId is required"
        )
    
    if not category:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message="category is required"
        )
    
    # Submit report
    result = submit_user_report(
        reporter_id=user_id,
        message_id=message_id,
        category=category,
        description=description
    )
    
    if not result.success:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message=result.error
        )
    
    return {
        "success": True,
        "reportId": result.report_id
    }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

@https_fn.on_call(
    memory=options.MemoryOption.MB_256,
    timeout_sec=30,
)
def get_rate_limits(req: https_fn.CallableRequest) -> dict:
    """
    Get current rate limit status for the authenticated user.
    
    Response:
        Dictionary with rate limit status for each limit type
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required"
        )
    
    return get_user_rate_limit_status(req.auth.uid)


# ============================================================================
# SCHEDULED FUNCTIONS
# ============================================================================

@scheduler_fn.on_schedule(
    schedule="every 5 minutes",
    memory=options.MemoryOption.MB_512,
    timeout_sec=300,
)
def process_queued_images(event: scheduler_fn.ScheduledEvent):
    """
    Process images that were queued due to moderation API failures.
    
    Runs every 5 minutes to retry moderation on queued images.
    """
    bucket = get_storage_bucket()
    
    # List all blobs in queued folder
    blobs = bucket.list_blobs(prefix="queued/")
    
    processed = 0
    max_process = 50  # Limit per run
    
    for blob in blobs:
        if processed >= max_process:
            break
        
        file_path = blob.name
        
        # Skip if not an image or if it's a folder marker
        if not file_path or file_path.endswith("/"):
            continue
        
        try:
            user_id, image_id = parse_storage_path(file_path)
        except ValueError:
            continue
        
        try:
            # Download and moderate
            image_content = blob.download_as_bytes()
            
            from image_moderation import moderate_image
            result = moderate_image(
                image_content=image_content,
                user_id=user_id,
                image_path=file_path,
                image_id=image_id
            )
            
            if result.action == ModerationAction.APPROVED:
                # Process and move
                processed_img = process_approved_image(image_content)
                upload_processed_images(processed_img, user_id, image_id)
                blob.delete()
                processed += 1
                
            elif result.action == ModerationAction.BLOCKED:
                delete_blocked_image(file_path)
                processed += 1
                
            # If still queued (API failed again), leave it for next run
            
        except Exception as e:
            print(f"Error processing queued image {file_path}: {e}")
    
    print(f"Processed {processed} queued images")


@scheduler_fn.on_schedule(
    schedule="every 24 hours",
    memory=options.MemoryOption.MB_256,
    timeout_sec=120,
)
def cleanup_rate_limits_scheduled(event: scheduler_fn.ScheduledEvent):
    """
    Clean up expired rate limit documents.
    
    Runs daily to remove old rate limit entries.
    """
    deleted = cleanup_expired_rate_limits(days_old=1)
    print(f"Cleaned up {deleted} expired rate limit documents")


# ============================================================================
# ADMIN FUNCTIONS (for Firebase Console / admin SDK usage)
# ============================================================================

@https_fn.on_call(
    memory=options.MemoryOption.MB_256,
    timeout_sec=30,
)
def get_moderation_stats(req: https_fn.CallableRequest) -> dict:
    """
    Get moderation statistics (admin only).
    
    Note: In production, add admin role verification.
    
    Response:
        Dictionary with moderation and report statistics
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required"
        )
    
    # TODO: Add admin role check
    # For now, return report stats
    return get_report_stats()
