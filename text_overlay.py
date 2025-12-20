"""
Text overlay module for adding title and author text to book cover images.
"""

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO


def add_text_overlay_to_image(image_bytes: bytes, title: str, author: str = None) -> bytes:
    """
    Add title and author text overlay to a book cover image.
    
    Args:
        image_bytes: The source image as bytes
        title: The book title to overlay
        author: The author name to overlay (optional)
    
    Returns:
        The modified image as PNG bytes
    """
    # Load image
    img = Image.open(BytesIO(image_bytes)).convert('RGBA')
    width, height = img.size
    
    # Create drawing context
    draw = ImageDraw.Draw(img)
    
    # Calculate font sizes based on image dimensions
    title_font_size = int(width * 0.08)
    author_font_size = int(width * 0.05)
    
    # Try to load a nice font, fall back to default
    try:
        title_font = ImageFont.truetype("arial.ttf", title_font_size)
        author_font = ImageFont.truetype("arial.ttf", author_font_size)
    except (IOError, OSError):
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", title_font_size)
            author_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", author_font_size)
        except (IOError, OSError):
            title_font = ImageFont.load_default()
            author_font = ImageFont.load_default()
    
    # Text positioning - title near top, author near bottom
    margin = int(width * 0.05)
    
    # Draw title with shadow effect
    title_y = int(height * 0.08)
    
    # Get title bounding box for centering
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    
    # Draw shadow
    shadow_offset = 2
    draw.text((title_x + shadow_offset, title_y + shadow_offset), title, font=title_font, fill=(0, 0, 0, 180))
    # Draw title
    draw.text((title_x, title_y), title, font=title_font, fill=(255, 255, 255, 255))
    
    # Draw author if provided
    if author:
        author_y = int(height * 0.88)
        
        # Get author bounding box for centering
        author_bbox = draw.textbbox((0, 0), author, font=author_font)
        author_width = author_bbox[2] - author_bbox[0]
        author_x = (width - author_width) // 2
        
        # Draw shadow
        draw.text((author_x + shadow_offset, author_y + shadow_offset), author, font=author_font, fill=(0, 0, 0, 180))
        # Draw author
        draw.text((author_x, author_y), author, font=author_font, fill=(255, 255, 255, 255))
    
    # Convert back to bytes
    output = BytesIO()
    img.convert('RGB').save(output, format='PNG')
    output.seek(0)
    return output.getvalue()
