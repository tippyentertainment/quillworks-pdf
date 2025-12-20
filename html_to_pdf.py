"""
HTML to PDF conversion using WeasyPrint
Provides high-quality PDF generation from HTML with full CSS support
"""

from flask import jsonify
from io import BytesIO
import requests

# Don't import WeasyPrint at module import time: its Python package
# depends on native shared libraries (gobject, pango, cairo, etc.)
# which may not be present in the runtime image and will raise
# OSError via cffi.dlopen. Defer imports to runtime when a conversion
# is requested so the application can boot even when those libs are
# missing.
WEASYPRINT_AVAILABLE = False

# Try to import WeasyPrint at module level, but don't fail if it's not available
try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    HTML = None
    CSS = None
    FontConfiguration = None


def html_to_pdf(html_content, base_url=None):
    """
    Convert HTML string to PDF bytes
    
    Args:
        html_content: HTML string with embedded CSS
        base_url: Base URL for resolving relative URLs (optional)
    
    Returns:
        BytesIO buffer containing PDF data
    """
    if not WEASYPRINT_AVAILABLE:
        raise ImportError("WeasyPrint is not installed. Install with: pip install weasyprint")
    
    # Configure fonts
    font_config = FontConfiguration()
    
    # Create HTML object
    html = HTML(string=html_content, base_url=base_url)
    
    # Additional CSS for enforcing 1.2 line-height on chapter content only
    print_css = CSS(string='''
        .chapter-content, .chapter-content p, .chapter-content div,
        .chapter-title, .chapter-number, .chapter-name {
            line-height: 1.2 !important;
        }
        
        /* Ensure page breaks work properly */
        .page-break, .chapter, .title-page, .blank-page,
        .dedication-page, .about-page, .toc-page {
            page-break-after: always;
        }
    ''', font_config=font_config)
    
    # Generate PDF
    pdf_buffer = BytesIO()
    html.write_pdf(pdf_buffer, stylesheets=[print_css], font_config=font_config)
    pdf_buffer.seek(0)
    
    return pdf_buffer


def fetch_and_convert_html_to_pdf(html_url):
    """
    Fetch HTML from URL and convert to PDF
    
    Args:
        html_url: URL of HTML page to convert
    
    Returns:
        BytesIO buffer containing PDF data
    """
    try:
        # Fetch HTML content
        response = requests.get(html_url, timeout=30)
        response.raise_for_status()
        html_content = response.text
        
        # Convert to PDF
        return html_to_pdf(html_content, base_url=html_url)
    
    except requests.RequestException as e:
        raise Exception(f"Failed to fetch HTML from {html_url}: {str(e)}")
    except Exception as e:
        raise Exception(f"Failed to convert HTML to PDF: {str(e)}")
