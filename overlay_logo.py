"""
Logo overlay module for compositing logo images onto base images.
"""

import requests
from PIL import Image
from io import BytesIO


def download_image(url: str) -> bytes:
    """
    Download an image from a URL.
    
    Args:
        url: The URL of the image to download
    
    Returns:
        The image data as bytes
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def overlay_logo_on_image(base_image_bytes: bytes, logo_image_bytes: bytes, position: str = 'top-left') -> bytes:
    """
    Overlay a logo image onto a base image at the specified position.
    
    Args:
        base_image_bytes: The base image as bytes
        logo_image_bytes: The logo image as bytes
        position: Where to place the logo. Options: 'top-left', 'top-right', 
                  'bottom-left', 'bottom-right', 'center'
    
    Returns:
        The composited image as PNG bytes
    """
    # Load images
    base_img = Image.open(BytesIO(base_image_bytes)).convert('RGBA')
    logo_img = Image.open(BytesIO(logo_image_bytes)).convert('RGBA')
    
    base_width, base_height = base_img.size
    logo_width, logo_height = logo_img.size
    
    # Scale logo if it's too large (max 20% of base image width)
    max_logo_width = int(base_width * 0.2)
    if logo_width > max_logo_width:
        scale = max_logo_width / logo_width
        new_width = int(logo_width * scale)
        new_height = int(logo_height * scale)
        logo_img = logo_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        logo_width, logo_height = logo_img.size
    
    # Calculate position
    margin = int(base_width * 0.03)  # 3% margin
    
    if position == 'top-left':
        x, y = margin, margin
    elif position == 'top-right':
        x, y = base_width - logo_width - margin, margin
    elif position == 'bottom-left':
        x, y = margin, base_height - logo_height - margin
    elif position == 'bottom-right':
        x, y = base_width - logo_width - margin, base_height - logo_height - margin
    elif position == 'center':
        x, y = (base_width - logo_width) // 2, (base_height - logo_height) // 2
    else:
        # Default to top-left
        x, y = margin, margin
    
    # Composite logo onto base image
    base_img.paste(logo_img, (x, y), logo_img)
    
    # Convert back to bytes
    output = BytesIO()
    base_img.convert('RGB').save(output, format='PNG')
    output.seek(0)
    return output.getvalue()
