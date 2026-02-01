"""
Unit tests for image processing module.
"""

import pytest
from io import BytesIO

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image

from image_processing import (
    compress_image,
    generate_thumbnail,
    process_approved_image,
    get_image_format,
    should_use_png,
    get_image_info,
    DEFAULT_THUMBNAIL_SIZE,
    DEFAULT_COMPRESSED_MAX_SIZE,
)


def create_test_image(width: int, height: int, mode: str = 'RGB', format: str = 'JPEG') -> bytes:
    """Create a test image of specified size."""
    img = Image.new(mode, (width, height), color='blue')
    output = BytesIO()
    if format == 'JPEG' and mode == 'RGBA':
        img = img.convert('RGB')
    img.save(output, format=format)
    output.seek(0)
    return output.read()


class TestCompressImage:
    """Tests for image compression."""
    
    def test_compress_small_image(self):
        """Small images should not be resized."""
        image_bytes = create_test_image(100, 100)
        
        compressed, format_used, size = compress_image(image_bytes)
        
        assert size == (100, 100)
        assert format_used == 'JPEG'
        assert len(compressed) > 0
    
    def test_compress_large_image(self):
        """Large images should be resized to max dimension."""
        image_bytes = create_test_image(3000, 2000)
        
        compressed, format_used, size = compress_image(
            image_bytes, 
            max_dimension=(1920, 1920)
        )
        
        # Should be scaled down proportionally
        assert size[0] <= 1920
        assert size[1] <= 1920
    
    def test_compress_maintains_aspect_ratio(self):
        """Compression should maintain aspect ratio."""
        # 2:1 aspect ratio
        image_bytes = create_test_image(4000, 2000)
        
        compressed, format_used, size = compress_image(
            image_bytes,
            max_dimension=(1920, 1920)
        )
        
        # Should maintain 2:1 ratio (approximately)
        ratio = size[0] / size[1]
        assert 1.9 < ratio < 2.1
    
    def test_compress_already_small(self):
        """Image already smaller than max should not be upscaled."""
        image_bytes = create_test_image(500, 500)
        
        compressed, format_used, size = compress_image(
            image_bytes,
            max_dimension=(1920, 1920)
        )
        
        assert size == (500, 500)


class TestGenerateThumbnail:
    """Tests for thumbnail generation."""
    
    def test_thumbnail_size(self):
        """Thumbnail should be within specified size."""
        image_bytes = create_test_image(1000, 800)
        
        thumbnail, size = generate_thumbnail(
            image_bytes,
            size=(200, 200)
        )
        
        assert size[0] <= 200
        assert size[1] <= 200
        assert len(thumbnail) > 0
    
    def test_thumbnail_maintains_aspect_ratio(self):
        """Thumbnail should maintain aspect ratio."""
        # 4:3 aspect ratio
        image_bytes = create_test_image(800, 600)
        
        thumbnail, size = generate_thumbnail(
            image_bytes,
            size=(200, 200)
        )
        
        # Should maintain 4:3 ratio
        ratio = size[0] / size[1]
        assert 1.2 < ratio < 1.4
    
    def test_thumbnail_small_image(self):
        """Small image thumbnail should not be upscaled."""
        image_bytes = create_test_image(50, 50)
        
        thumbnail, size = generate_thumbnail(
            image_bytes,
            size=(200, 200)
        )
        
        assert size == (50, 50)


class TestProcessApprovedImage:
    """Tests for the full processing pipeline."""
    
    def test_process_creates_all_versions(self):
        """Processing should create compressed and thumbnail versions."""
        image_bytes = create_test_image(1000, 800)
        
        result = process_approved_image(image_bytes)
        
        assert result.original_bytes == image_bytes
        assert len(result.compressed_bytes) > 0
        assert len(result.thumbnail_bytes) > 0
        assert result.original_size == (1000, 800)
    
    def test_process_reduces_size(self):
        """Processing should reduce file size."""
        # Create a large image
        image_bytes = create_test_image(3000, 3000)
        
        result = process_approved_image(image_bytes)
        
        # Compressed should be smaller dimension
        assert result.compressed_size[0] <= DEFAULT_COMPRESSED_MAX_SIZE[0]
        assert result.compressed_size[1] <= DEFAULT_COMPRESSED_MAX_SIZE[1]
        
        # Thumbnail should be much smaller
        assert result.thumbnail_size[0] <= DEFAULT_THUMBNAIL_SIZE[0]
        assert result.thumbnail_size[1] <= DEFAULT_THUMBNAIL_SIZE[1]


class TestImageFormat:
    """Tests for format detection."""
    
    def test_detect_jpeg_format(self):
        """JPEG format should be detected."""
        image_bytes = create_test_image(100, 100, format='JPEG')
        img = Image.open(BytesIO(image_bytes))
        
        format_detected = get_image_format(img)
        
        assert format_detected == 'JPEG'
    
    def test_detect_png_format(self):
        """PNG format should be detected."""
        image_bytes = create_test_image(100, 100, mode='RGB', format='PNG')
        img = Image.open(BytesIO(image_bytes))
        
        format_detected = get_image_format(img)
        
        assert format_detected == 'PNG'


class TestShouldUsePng:
    """Tests for PNG decision logic."""
    
    def test_rgb_no_png(self):
        """RGB images should not use PNG."""
        image_bytes = create_test_image(100, 100, mode='RGB')
        img = Image.open(BytesIO(image_bytes))
        
        assert should_use_png(img) is False
    
    def test_rgba_with_transparency_uses_png(self):
        """RGBA with transparency should use PNG."""
        # Create RGBA image with transparency
        img = Image.new('RGBA', (100, 100), color=(255, 0, 0, 128))
        
        assert should_use_png(img) is True
    
    def test_rgba_fully_opaque_no_png(self):
        """RGBA that's fully opaque should not use PNG."""
        # Create RGBA image that's fully opaque
        img = Image.new('RGBA', (100, 100), color=(255, 0, 0, 255))
        
        assert should_use_png(img) is False


class TestGetImageInfo:
    """Tests for image info extraction."""
    
    def test_get_info_jpeg(self):
        """Should extract info from JPEG."""
        image_bytes = create_test_image(800, 600)
        
        info = get_image_info(image_bytes)
        
        assert info['format'] == 'JPEG'
        assert info['size'] == (800, 600)
        assert info['width'] == 800
        assert info['height'] == 600
        assert info['bytes'] == len(image_bytes)
