"""
Image processing module for thumbnail generation and compression.

This module handles post-moderation image processing:
- Thumbnail generation for previews
- Image compression to reduce storage costs
- Format optimization
"""

import io
from typing import Optional, Tuple
from dataclasses import dataclass

from PIL import Image

from utils import get_storage_bucket, get_env_int


# Default configuration
DEFAULT_THUMBNAIL_SIZE = (200, 200)
DEFAULT_COMPRESSED_MAX_SIZE = (1920, 1920)  # Max dimension for compressed
DEFAULT_JPEG_QUALITY = 85
DEFAULT_THUMBNAIL_QUALITY = 75


@dataclass
class ProcessedImage:
    """Result of image processing."""
    original_bytes: bytes
    compressed_bytes: bytes
    thumbnail_bytes: bytes
    original_format: str
    compressed_format: str
    original_size: Tuple[int, int]
    compressed_size: Tuple[int, int]
    thumbnail_size: Tuple[int, int]


def get_image_format(image: Image.Image) -> str:
    """
    Get the format of an image, defaulting to JPEG.
    
    Args:
        image: PIL Image object
        
    Returns:
        Image format string (e.g., 'JPEG', 'PNG')
    """
    if image.format:
        return image.format
    # Default to JPEG for photos
    return 'JPEG'


def should_use_png(image: Image.Image) -> bool:
    """
    Determine if PNG should be used (for transparency).
    
    Args:
        image: PIL Image object
        
    Returns:
        True if PNG should be used
    """
    # Use PNG if image has alpha channel
    if image.mode in ('RGBA', 'LA', 'PA'):
        # Check if there's actual transparency
        if image.mode == 'RGBA':
            alpha = image.getchannel('A')
            # If all pixels are fully opaque, no need for PNG
            if alpha.getextrema() == (255, 255):
                return False
            return True
    return False


def compress_image(
    image_content: bytes,
    max_dimension: Tuple[int, int] = DEFAULT_COMPRESSED_MAX_SIZE,
    quality: int = DEFAULT_JPEG_QUALITY
) -> Tuple[bytes, str, Tuple[int, int]]:
    """
    Compress an image while maintaining quality.
    
    Args:
        image_content: Raw image bytes
        max_dimension: Maximum width/height
        quality: JPEG quality (1-100)
        
    Returns:
        Tuple of (compressed bytes, format, new size)
    """
    # Open image
    img = Image.open(io.BytesIO(image_content))
    original_size = img.size
    
    # Convert to RGB if necessary (for JPEG)
    use_png = should_use_png(img)
    
    if not use_png and img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    
    # Resize if larger than max dimension
    if img.width > max_dimension[0] or img.height > max_dimension[1]:
        img.thumbnail(max_dimension, Image.Resampling.LANCZOS)
    
    # Save to bytes
    output = io.BytesIO()
    
    if use_png:
        img.save(output, format='PNG', optimize=True)
        format_used = 'PNG'
    else:
        img.save(output, format='JPEG', quality=quality, optimize=True)
        format_used = 'JPEG'
    
    output.seek(0)
    return output.read(), format_used, img.size


def generate_thumbnail(
    image_content: bytes,
    size: Tuple[int, int] = DEFAULT_THUMBNAIL_SIZE,
    quality: int = DEFAULT_THUMBNAIL_QUALITY
) -> Tuple[bytes, Tuple[int, int]]:
    """
    Generate a thumbnail from an image.
    
    Args:
        image_content: Raw image bytes
        size: Thumbnail size (width, height)
        quality: JPEG quality for thumbnail
        
    Returns:
        Tuple of (thumbnail bytes, actual size)
    """
    # Open image
    img = Image.open(io.BytesIO(image_content))
    
    # Convert to RGB if necessary
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    
    # Create thumbnail (maintains aspect ratio)
    img.thumbnail(size, Image.Resampling.LANCZOS)
    
    # Save to bytes as JPEG
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=quality, optimize=True)
    output.seek(0)
    
    return output.read(), img.size


def process_approved_image(
    image_content: bytes,
    thumbnail_size: Tuple[int, int] = DEFAULT_THUMBNAIL_SIZE,
    max_compressed_size: Tuple[int, int] = DEFAULT_COMPRESSED_MAX_SIZE,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    thumbnail_quality: int = DEFAULT_THUMBNAIL_QUALITY
) -> ProcessedImage:
    """
    Process an approved image: compress and generate thumbnail.
    
    Args:
        image_content: Raw image bytes
        thumbnail_size: Size for thumbnail
        max_compressed_size: Max size for compressed version
        jpeg_quality: Quality for compressed JPEG
        thumbnail_quality: Quality for thumbnail JPEG
        
    Returns:
        ProcessedImage with all versions
    """
    # Get original info
    original_img = Image.open(io.BytesIO(image_content))
    original_format = get_image_format(original_img)
    original_size = original_img.size
    
    # Compress
    compressed_bytes, compressed_format, compressed_size = compress_image(
        image_content,
        max_compressed_size,
        jpeg_quality
    )
    
    # Generate thumbnail
    thumbnail_bytes, thumbnail_size_actual = generate_thumbnail(
        image_content,
        thumbnail_size,
        thumbnail_quality
    )
    
    return ProcessedImage(
        original_bytes=image_content,
        compressed_bytes=compressed_bytes,
        thumbnail_bytes=thumbnail_bytes,
        original_format=original_format,
        compressed_format=compressed_format,
        original_size=original_size,
        compressed_size=compressed_size,
        thumbnail_size=thumbnail_size_actual
    )


def upload_processed_images(
    processed: ProcessedImage,
    user_id: str,
    image_id: str,
    bucket_name: Optional[str] = None
) -> dict:
    """
    Upload processed images to Firebase Storage.
    
    Args:
        processed: ProcessedImage object with all versions
        user_id: User ID
        image_id: Image ID
        bucket_name: Optional bucket name
        
    Returns:
        Dictionary with paths to all uploaded versions
    """
    bucket = get_storage_bucket(bucket_name)
    
    # Determine file extensions
    compressed_ext = 'png' if processed.compressed_format == 'PNG' else 'jpg'
    
    # Strip existing extension from image_id if present
    base_image_id = image_id.rsplit('.', 1)[0] if '.' in image_id else image_id
    
    # Upload compressed version to /approved/
    approved_path = f"approved/{user_id}/{base_image_id}.{compressed_ext}"
    approved_blob = bucket.blob(approved_path)
    approved_blob.upload_from_string(
        processed.compressed_bytes,
        content_type=f"image/{compressed_ext}"
    )
    
    # Upload thumbnail to /thumbnails/
    thumbnail_path = f"thumbnails/{user_id}/{base_image_id}.jpg"
    thumbnail_blob = bucket.blob(thumbnail_path)
    thumbnail_blob.upload_from_string(
        processed.thumbnail_bytes,
        content_type="image/jpeg"
    )
    
    return {
        "approved_path": approved_path,
        "thumbnail_path": thumbnail_path,
        "compressed_size": processed.compressed_size,
        "thumbnail_size": processed.thumbnail_size,
        "compressed_bytes": len(processed.compressed_bytes),
        "thumbnail_bytes": len(processed.thumbnail_bytes),
    }


def get_image_info(image_content: bytes) -> dict:
    """
    Get information about an image.
    
    Args:
        image_content: Raw image bytes
        
    Returns:
        Dictionary with image info
    """
    img = Image.open(io.BytesIO(image_content))
    
    return {
        "format": get_image_format(img),
        "mode": img.mode,
        "size": img.size,
        "width": img.width,
        "height": img.height,
        "has_transparency": should_use_png(img),
        "bytes": len(image_content),
    }
