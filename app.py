"""
Simple PDF Generation Service for QuillWorks.AI
Deploy this on Railway, Render, Fly.io, or any Python hosting platform.

Install dependencies:
pip install flask weasyprint python-dotenv

Run locally:
python app.py

Deploy to Railway/Render with Procfile:
web: gunicorn app:app
"""

from flask import Flask, request, jsonify, send_file, Response
from io import BytesIO
import os
import json
import shutil
import tempfile
import subprocess
import requests

# ReportLab imports
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.pdfmetrics import stringWidth
    REPORTLAB_AVAILABLE = True
    # Default font family - can be customized
    FONT_FAMILY = 'Helvetica'
except ImportError:
    REPORTLAB_AVAILABLE = False
    FONT_FAMILY = 'Helvetica'
    print("WARNING: ReportLab not available, PDF generation endpoints will fail")

try:
    from generate_book_docx import generate_book_docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    print("WARNING: python-docx not available, DOCX generation disabled")

try:
    from pypdf import PdfReader
    PDF_EXTRACTION_AVAILABLE = True
except ImportError:
    PDF_EXTRACTION_AVAILABLE = False
    print("WARNING: pypdf not available, PDF text extraction disabled")

try:
    from html_to_pdf import html_to_pdf, fetch_and_convert_html_to_pdf
    HTML_TO_PDF_AVAILABLE = True
except ImportError:
    HTML_TO_PDF_AVAILABLE = False
    print("WARNING: HTML to PDF conversion not available")

try:
    from docx import Document
    DOCX_EXTRACTION_AVAILABLE = True
except ImportError:
    DOCX_EXTRACTION_AVAILABLE = False
    print("WARNING: python-docx not available for text extraction")

try:
    from generate_flyer_pdf import generate_flyer_pdf
    from overlay_logo import overlay_logo_on_image, download_image
    FLYER_PDF_AVAILABLE = True
except ImportError:
    FLYER_PDF_AVAILABLE = False
    print("WARNING: Flyer PDF generation not available")

try:
    from text_overlay import add_text_overlay_to_image
    TEXT_OVERLAY_AVAILABLE = True
except ImportError:
    TEXT_OVERLAY_AVAILABLE = False
    print("WARNING: Text overlay not available")

# rembg is lazy-loaded to avoid slow startup from numba compilation
REMBG_AVAILABLE = True
_rembg_remove = None

def get_rembg_remove():
    global _rembg_remove, REMBG_AVAILABLE
    if _rembg_remove is None:
        try:
            from rembg import remove
            _rembg_remove = remove
        except ImportError:
            REMBG_AVAILABLE = False
            print("WARNING: rembg not available")
    return _rembg_remove

try:
    from generate_epub import build_epub
    EPUB_AVAILABLE = True
except ImportError:
    EPUB_AVAILABLE = False
    print("WARNING: EPUB generation not available")

try:
    from design_service import (
        generate_nano_banana_design,
        upscale_with_esrgan,
        build_prompt,
        write_candidate_files,
        list_candidates,
        mark_selected,
        apply_to_project,
        BASE_DIR,
        attach_cloudflare_domain,
    )

    # Endpoint to automate Cloudflare domain attachment
    @app.route('/cloudflare/attach-domain', methods=['POST'])
    def cloudflare_attach_domain():
        """Attach a domain to a Cloudflare Pages project using Wrangler CLI."""
        data = request.json
        project_name = data.get('project_name')
        domain = data.get('domain')
        if not project_name or not domain:
            return jsonify({'error': 'project_name and domain are required'}), 400
        try:
            attach_cloudflare_domain(project_name, domain)
            return jsonify({'ok': True, 'message': f'Domain {domain} attached to project {project_name}.'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    # Check if ATLASCLOUD_API_KEY is set
    if os.environ.get("ATLASCLOUD_API_KEY"):
        DESIGN_SERVICE_AVAILABLE = True
    else:
        DESIGN_SERVICE_AVAILABLE = False
        print("WARNING: Design service module loaded but ATLASCLOUD_API_KEY not set")
except ImportError as e:
    DESIGN_SERVICE_AVAILABLE = False
    print(f"WARNING: Design service not available: {e}")

app = Flask(__name__)

# Add CORS headers for design service endpoints
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy', 
        'service': 'pdf-generator',
        'capabilities': {
            'docx_generation': DOCX_AVAILABLE,
            'pdf_extraction': PDF_EXTRACTION_AVAILABLE,
            'docx_extraction': DOCX_EXTRACTION_AVAILABLE,
            'html_to_pdf': HTML_TO_PDF_AVAILABLE,
            'flyer_pdf': FLYER_PDF_AVAILABLE,
            'text_overlay': TEXT_OVERLAY_AVAILABLE,
            'rembg': REMBG_AVAILABLE,
            'epub_generation': EPUB_AVAILABLE,
            'design_service': DESIGN_SERVICE_AVAILABLE,
            'reportlab': REPORTLAB_AVAILABLE,
            'pages_deploy': True
        }
    })
@app.route('/designs/generate', methods=['POST', 'OPTIONS'])
def generate_design():
    """Generate a new design theme."""
    if not DESIGN_SERVICE_AVAILABLE:
        return jsonify({'error': 'Design service not available'}), 500
    
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        industry = data.get('industry', 'technology')
        prompt_override = data.get('prompt_override')

        prompt = build_prompt(industry, prompt_override)
        base_img = generate_nano_banana_design(prompt)
        hi_img = upscale_with_esrgan(base_img, scale=2)

        import uuid
        theme_id = str(uuid.uuid4())
        version = 1

        manifest = write_candidate_files(theme_id, version, hi_img, industry, prompt)

        return jsonify({
            'themeId': theme_id,
            'version': version,
            'previewPng': manifest['master_png'],
            'manifest': manifest,
        })
    except Exception as e:
        error_msg = str(e) or "Unknown error occurred"
        print(f"Error generating design: {error_msg}")
        import traceback
        traceback.print_exc()
        # Return a more user-friendly error message
        if "ATLASCLOUD_API_KEY" in error_msg:
            return jsonify({'error': 'Design service API key not configured'}), 500
        elif "timeout" in error_msg.lower():
            return jsonify({'error': 'Design generation timed out. Please try again.'}), 504
        else:
            return jsonify({'error': f'Design generation failed: {error_msg}'}), 500


@app.route('/designs/list', methods=['GET', 'OPTIONS'])
def list_designs():
    """List all generated design candidates."""
    if not DESIGN_SERVICE_AVAILABLE:
        return jsonify({'error': 'Design service not available', 'items': []}), 500
    
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        items = list_candidates()
        return jsonify({'items': items})
    except Exception as e:
        print(f"Error listing designs: {str(e)}")
        return jsonify({'error': str(e), 'items': []}), 500


@app.route('/designs/preview', methods=['GET', 'OPTIONS'])
def get_preview_image():
    """Serve preview images from the designs storage directory."""
    if not DESIGN_SERVICE_AVAILABLE:
        return jsonify({'error': 'Design service not available'}), 500
    
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        path = request.args.get('path')
        if not path:
            return jsonify({'error': 'Path parameter required'}), 400
        
        # Security: ensure path is within BASE_DIR
        full_path = BASE_DIR / path
        if not str(full_path.resolve()).startswith(str(BASE_DIR.resolve())):
            return jsonify({'error': 'Invalid path'}), 403
        
        if not full_path.exists():
            return jsonify({'error': 'Preview image not found'}), 404
        
        return send_file(full_path, mimetype='image/png')
    except Exception as e:
        print(f"Error serving preview: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/designs/select', methods=['POST', 'OPTIONS'])
def select_design():
    """Select and apply a design to the project."""
    if not DESIGN_SERVICE_AVAILABLE:
        return jsonify({'error': 'Design service not available'}), 500
    
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        theme_id = data.get('theme_id')
        version = data.get('version')
        
        if not theme_id or version is None:
            return jsonify({'error': 'theme_id and version required'}), 400
        
        mark_selected(theme_id, version)
        applied = apply_to_project(theme_id, version)
        
        return jsonify({
            'ok': True,
            'applied': applied
        })
    except Exception as e:
        print(f"Error selecting design: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/convert-html-to-pdf', methods=['POST'])
def convert_html_to_pdf():
    """Convert HTML content or URL to PDF using WeasyPrint"""
    if not HTML_TO_PDF_AVAILABLE:
        return jsonify({'error': 'HTML to PDF conversion not available. Install weasyprint.'}), 500
    
    try:
        data = request.json
        
        # Check if HTML content is provided directly
        if 'html' in data:
            html_content = data['html']
            base_url = data.get('base_url')
            pdf_buffer = html_to_pdf(html_content, base_url)
        
        # Or fetch from URL
        elif 'url' in data:
            html_url = data['url']
            pdf_buffer = fetch_and_convert_html_to_pdf(html_url)
        
        else:
            return jsonify({'error': 'Either "html" or "url" must be provided'}), 400
        
        # Get filename from request or use default
        filename = data.get('filename', 'document.pdf')
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        return jsonify({'error': f'HTML to PDF conversion failed: {str(e)}'}), 500

@app.route('/extract-text', methods=['POST'])
def extract_text():
    """Extract text from PDF or DOCX files"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = file.filename.lower()
        
        # Extract text based on file type
        if filename.endswith('.pdf'):
            if not PDF_EXTRACTION_AVAILABLE:
                return jsonify({'error': 'PDF text extraction not available'}), 500
            
            try:
                pdf_reader = PdfReader(file)
                text_parts = []
                for page in pdf_reader.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                
                extracted_text = '\n\n'.join(text_parts)
                
                if not extracted_text.strip():
                    return jsonify({'error': 'No text could be extracted from the PDF. The file may be image-based or encrypted.'}), 400
                
                return jsonify({'text': extracted_text})
                
            except Exception as e:
                return jsonify({'error': f'Failed to extract text from PDF: {str(e)}'}), 500
        
        elif filename.endswith('.docx'):
            if not DOCX_EXTRACTION_AVAILABLE:
                return jsonify({'error': 'DOCX text extraction not available'}), 500
            
            try:
                doc = Document(file)
                text_parts = []
                for paragraph in doc.paragraphs:
                    if paragraph.text.strip():
                        text_parts.append(paragraph.text)
                
                extracted_text = '\n\n'.join(text_parts)
                
                if not extracted_text.strip():
                    return jsonify({'error': 'No text could be extracted from the DOCX file.'}), 400
                
                return jsonify({'text': extracted_text})
                
            except Exception as e:
                return jsonify({'error': f'Failed to extract text from DOCX: {str(e)}'}), 500
        
        elif filename.endswith('.txt'):
            try:
                text = file.read().decode('utf-8')
                if not text.strip():
                    return jsonify({'error': 'The text file is empty.'}), 400
                return jsonify({'text': text})
            except Exception as e:
                return jsonify({'error': f'Failed to read text file: {str(e)}'}), 500
        
        else:
            return jsonify({'error': 'Unsupported file type. Please upload PDF, DOCX, or TXT files.'}), 400
        
    except Exception as e:
        return jsonify({'error': f'Text extraction failed: {str(e)}'}), 500


@app.route('/generate-flyer-pdf', methods=['POST'])
def generate_flyer_pdf_endpoint():
    """Generate PDF for flyers"""
    if not FLYER_PDF_AVAILABLE:
        return jsonify({'error': 'Flyer PDF generation not available'}), 500
    
    try:
        data = request.json
        flyer_data = data.get('data', {})
        
        # Generate PDF
        pdf_buffer = generate_flyer_pdf(flyer_data)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{flyer_data.get('service', 'flyer').replace(' ', '_')}_flyer.pdf"
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/overlay-logo', methods=['POST'])
def overlay_logo_endpoint():
    """Overlay a logo image onto a base image at the specified position."""
    try:
        data = request.json
        base_image_url = data.get('base_image_url')
        logo_image_url = data.get('logo_image_url')
        position = data.get('position', 'top-left')
        
        if not base_image_url:
            return jsonify({'error': 'base_image_url is required'}), 400
        if not logo_image_url:
            return jsonify({'error': 'logo_image_url is required'}), 400
        
        print(f"Overlaying logo at {position}")
        print(f"Base image: {base_image_url}")
        print(f"Logo: {logo_image_url}")
        
        # Download images
        base_image_bytes = download_image(base_image_url)
        logo_image_bytes = download_image(logo_image_url)
        
        # Overlay logo
        result_bytes = overlay_logo_on_image(base_image_bytes, logo_image_bytes, position)
        
        # Return the composited image
        buffer = BytesIO(result_bytes)
        buffer.seek(0)
        return send_file(buffer, mimetype='image/png')
    except Exception as e:
        print(f"Error overlaying logo: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/add-text-overlay', methods=['POST'])
def add_text_overlay_endpoint():
    """Add title and author text overlay to a book cover image."""
    if not TEXT_OVERLAY_AVAILABLE:
        return jsonify({'error': 'Text overlay not available'}), 500
    
    try:
        data = request.json
        base_image_url = data.get('base_image_url')
        title = data.get('title')
        author = data.get('author')
        
        if not base_image_url:
            return jsonify({'error': 'base_image_url is required'}), 400
        if not title:
            return jsonify({'error': 'title is required'}), 400
        
        print(f"Adding text overlay to cover")
        print(f"Base image: {base_image_url}")
        print(f"Title: {title}")
        print(f"Author: {author}")
        
        # Download base image
        base_image_bytes = download_image(base_image_url)
        
        # Add text overlay
        result_bytes = add_text_overlay_to_image(base_image_bytes, title, author)
        
        # Return the image with text overlay
        buffer = BytesIO(result_bytes)
        buffer.seek(0)
        return send_file(buffer, mimetype='image/png')
    except Exception as e:
        print(f"Error adding text overlay: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/remove-background', methods=['POST'])
def remove_background():
    """Remove background from an image using rembg"""
    remove_fn = get_rembg_remove()
    if not REMBG_AVAILABLE or remove_fn is None:
        return jsonify({'error': 'rembg not available. Install rembg package.'}), 500
    
    try:
        data = request.json
        image_url = data.get('image_url')
        
        if not image_url:
            return jsonify({'error': 'image_url is required'}), 400
        
        print(f"Removing background from: {image_url}")
        
        # Download image
        image_bytes = download_image(image_url)
        
        # Remove background using rembg
        input_buffer = BytesIO(image_bytes)
        output_buffer = BytesIO()
        
        output_buffer.write(remove_fn(input_buffer.read()))
        output_buffer.seek(0)
        
        print(f"Background removed successfully")
        
        # Return the image with transparent background
        return send_file(output_buffer, mimetype='image/png')
    except Exception as e:
        print(f"Error removing background: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/generate-epub', methods=['POST'])
def generate_epub_endpoint():
    """Generate EPUB from interior and cover PDFs"""
    if not EPUB_AVAILABLE:
        return jsonify({'error': 'EPUB generation not available. Install ebooklib, pdfplumber, and pdf2image.'}), 500
    
    try:
        data = request.json
        interior_pdf_url = data.get('interior_pdf_url')
        title = data.get('title')
        author = data.get('author')
        cover_pdf_url = data.get('cover_pdf_url')
        description = data.get('description')
        language = data.get('language', 'en')
        
        if not interior_pdf_url:
            return jsonify({'error': 'interior_pdf_url is required'}), 400
        if not title:
            return jsonify({'error': 'title is required'}), 400
        if not author:
            return jsonify({'error': 'author is required'}), 400
        
        print(f"[EPUB] Generating EPUB for: {title} by {author}")
        print(f"[EPUB] Interior PDF: {interior_pdf_url}")
        if cover_pdf_url:
            print(f"[EPUB] Cover PDF: {cover_pdf_url}")
        
        # Generate EPUB
        epub_bytes = build_epub(
            interior_pdf_url=interior_pdf_url,
            title=title,
            author=author,
            cover_pdf_url=cover_pdf_url,
            description=description,
            language=language
        )
        
        # Return EPUB file
        buffer = BytesIO(epub_bytes)
        buffer.seek(0)
        
        filename = f"{title.replace(' ', '_')}.epub"
        
        return send_file(
            buffer,
            mimetype='application/epub+zip',
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        print(f"Error generating EPUB: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/generate-recipe-book-pdf', methods=['POST'])
def generate_recipe_book_pdf():
    """Generate PDF for recipe books with two-page spreads matching the preview"""
    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'ReportLab not available. Install reportlab package.'}), 500
    
    try:
        data = request.json
        recipe_book_data = data.get('data', {})
        
        # Create PDF
        buffer = BytesIO()
        
        # 8.5 x 11 inches portrait
        page_width, page_height = 8.5*inch, 11*inch
        
        # Get page color
        page_color_name = recipe_book_data.get('page_color', 'cream')
        page_colors = {
            'white': colors.white,
            'cream': colors.Color(1, 0.996, 0.941),
            'off-white': colors.Color(0.973, 0.973, 0.973),
            'ivory': colors.Color(1, 1, 0.941)
        }
        page_color = page_colors.get(page_color_name, page_colors['cream'])
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=(page_width, page_height),
            leftMargin=0.5*inch,
            rightMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )
        
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles matching the preview
        title_style = ParagraphStyle(
            'RecipeTitle',
            parent=styles['Title'],
            fontName='Inter' if 'Inter' in [f.name for f in pdfmetrics.getRegisteredFontNames()] else 'Helvetica-Bold',
            fontSize=16,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=12
        )
        
        heading_style = ParagraphStyle(
            'RecipeHeading',
            parent=styles['Heading2'],
            fontName='Inter' if 'Inter' in [f.name for f in pdfmetrics.getRegisteredFontNames()] else 'Helvetica-Bold',
            fontSize=12,
            textColor=colors.black,
            spaceAfter=8,
            spaceBefore=0
        )
        
        did_you_know_heading = ParagraphStyle(
            'DidYouKnowHeading',
            parent=styles['Heading2'],
            fontName='Inter' if 'Inter' in [f.name for f in pdfmetrics.getRegisteredFontNames()] else 'Helvetica-Bold',
            fontSize=12,
            textColor=colors.HexColor('#9a3412'),
            spaceAfter=8,
            spaceBefore=0
        )
        
        body_style = ParagraphStyle(
            'RecipeBody',
            parent=styles['Normal'],
            fontName='Georgia',
            fontSize=9,
            leading=13.5,
            textColor=colors.HexColor('#333333'),
            alignment=TA_LEFT
        )
        
        recipe_name_footer = ParagraphStyle(
            'RecipeNameFooter',
            parent=styles['Normal'],
            fontName='Georgia',
            fontSize=8,
            textColor=colors.HexColor('#666666'),
            alignment=TA_CENTER
        )
        
        recipe_header_title = ParagraphStyle(
            'RecipeHeaderTitle',
            parent=styles['Normal'],
            fontName='Inter' if 'Inter' in [f.name for f in pdfmetrics.getRegisteredFontNames()] else 'Helvetica-Bold',
            fontSize=14,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=4
        )
        
        recipe_header_details = ParagraphStyle(
            'RecipeHeaderDetails',
            parent=styles['Normal'],
            fontName='Georgia',
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            alignment=TA_CENTER,
            spaceAfter=12
        )
        
        # Title page
        story.append(Spacer(1, 2*inch))
        story.append(Paragraph(recipe_book_data.get('book_title', 'Recipe Book'), title_style))
        if recipe_book_data.get('subheading'):
            subheading_style = ParagraphStyle(
                'Subheading',
                parent=body_style,
                fontName='Inter' if 'Inter' in [f.name for f in pdfmetrics.getRegisteredFontNames()] else 'Helvetica',
                fontSize=14,
                fontStyle='italic',
                alignment=TA_CENTER
            )
            story.append(Paragraph(recipe_book_data['subheading'], subheading_style))
        story.append(Spacer(1, 0.5*inch))
        author_style = ParagraphStyle(
            'Author',
            parent=body_style,
            fontName='Inter' if 'Inter' in [f.name for f in pdfmetrics.getRegisteredFontNames()] else 'Helvetica',
            fontSize=14,
            alignment=TA_CENTER
        )
        story.append(Paragraph(f"by {recipe_book_data.get('author_name', 'Author')}", author_style))
        story.append(PageBreak())
        
        # Dedication page if present
        if recipe_book_data.get('dedication'):
            story.append(Spacer(1, 2*inch))
            dedication_style = ParagraphStyle(
                'Dedication',
                parent=body_style,
                fontName='Georgia',
                fontSize=12,
                textColor=colors.HexColor('#333333'),
                alignment=TA_CENTER,
                fontStyle='italic'
            )
            story.append(Paragraph(recipe_book_data['dedication'], dedication_style))
            story.append(PageBreak())
        
        # Table of Contents
        if recipe_book_data.get('recipes') and len(recipe_book_data.get('recipes', [])) > 0:
            story.append(Spacer(1, 1*inch))
            toc_title_style = ParagraphStyle(
                'TOCTitle',
                parent=styles['Heading1'],
                fontName='Inter' if 'Inter' in [f.name for f in pdfmetrics.getRegisteredFontNames()] else 'Helvetica-Bold',
                fontSize=16,
                textColor=colors.black,
                alignment=TA_CENTER,
                spaceAfter=20
            )
            story.append(Paragraph("Table of Contents", toc_title_style))
            
            toc_style = ParagraphStyle(
                'TOCEntry',
                parent=body_style,
                fontName='Georgia',
                fontSize=12,
                textColor=colors.HexColor('#333333'),
                alignment=TA_LEFT,
                spaceAfter=4
            )
            
            for idx, recipe in enumerate(recipe_book_data.get('recipes', [])):
                recipe_name = recipe.get('name', f'Recipe {idx + 1}')
                story.append(Paragraph(recipe_name, toc_style))
                if idx < len(recipe_book_data.get('recipes', [])) - 1:
                    story.append(Spacer(1, 2))
            
            story.append(PageBreak())
        
        # Track page numbers
        page_number = 1
        
        # Recipes as two-page spreads
        for recipe_idx, recipe in enumerate(recipe_book_data.get('recipes', [])):
            # LEFT PAGE - Image and History
            left_page_elements = []
            
            # Recipe image if available - adjusted for 8.5x11 portrait
            # Note: Image already contains recipe name, so no header needed
            if recipe.get('image_url'):
                try:
                    img_url = recipe['image_url']
                    if img_url.startswith('http'):
                        img_response = requests.get(img_url, timeout=10)
                        img_buffer = BytesIO(img_response.content)
                        # Image for portrait layout - maintain aspect ratio, slightly smaller to fit better
                        img = Image(img_buffer, width=7.5*inch, height=5.5*inch)
                        left_page_elements.append(img)
                        left_page_elements.append(Spacer(1, 4))
                except Exception as e:
                    print(f"Failed to load recipe image: {e}")
            
            # History section with "Did you know" heading
            if recipe.get('history'):
                left_page_elements.append(Paragraph("Did you know", did_you_know_heading))
                left_page_elements.append(Paragraph(recipe['history'], body_style))
            
            # Add left page elements
            for element in left_page_elements:
                story.append(element)
            
            # Force page break to start right page
            story.append(PageBreak())
            
            # RIGHT PAGE - Ingredients and Directions  
            right_page_elements = []
            
            # Add header with recipe title and details
            right_page_elements.append(Paragraph(f"<b>{recipe.get('name', 'Untitled Recipe')}</b>", recipe_header_title))
            
            # Create header details line
            header_parts = []
            if recipe.get('cooking_time'):
                header_parts.append(recipe['cooking_time'])
            if recipe.get('servings'):
                header_parts.append(f"{recipe['servings']} servings")
            
            if header_parts:
                header_details = '               '.join(header_parts)
                right_page_elements.append(Paragraph(header_details, recipe_header_details))
            else:
                right_page_elements.append(Spacer(1, 16))
            
            # Ingredients in 2 columns
            if recipe.get('ingredients'):
                right_page_elements.append(Paragraph("Ingredients", heading_style))
                ingredients = recipe['ingredients']
                if isinstance(ingredients, list):
                    # Create 2-column table for ingredients
                    ingredient_list = [ing.strip() for ing in ingredients if ing.strip()]
                    # Split into two columns
                    mid_point = (len(ingredient_list) + 1) // 2
                    col1 = ingredient_list[:mid_point]
                    col2 = ingredient_list[mid_point:]
                    
                    # Pad the shorter column
                    while len(col1) < len(col2):
                        col1.append('')
                    while len(col2) < len(col1):
                        col2.append('')
                    
                    # Create table data
                    table_data = []
                    for i in range(len(col1)):
                        row = [
                            Paragraph(f"• {col1[i]}" if col1[i] else '', body_style),
                            Paragraph(f"• {col2[i]}" if col2[i] else '', body_style)
                        ]
                        table_data.append(row)
                    
                    # Create table
                    ingredients_table = Table(table_data, colWidths=[3.5*inch, 3.5*inch])
                    ingredients_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                        ('TOPPADDING', (0, 0), (-1, -1), 2),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                    ]))
                    right_page_elements.append(ingredients_table)
                    right_page_elements.append(Spacer(1, 6))
            
            # Preparation Steps
            raw_prep_steps = recipe.get('preparation_steps', '')
            if raw_prep_steps:
                right_page_elements.append(Paragraph("Preparation Steps", heading_style))
                # Split by newlines first
                lines = [s.strip() for s in raw_prep_steps.split('\n') if s.strip()]
                # Then flatten by splitting on commas to match preview behavior
                all_steps = []
                for line in lines:
                    individual_steps = [s.strip() for s in line.split(',') if s.strip()]
                    all_steps.extend(individual_steps)
                
                # Create 2-column table for preparation steps to match preview
                mid_point = (len(all_steps) + 1) // 2
                col1_steps = all_steps[:mid_point]
                col2_steps = all_steps[mid_point:]
                
                # Pad the shorter column
                while len(col1_steps) < len(col2_steps):
                    col1_steps.append('')
                while len(col2_steps) < len(col1_steps):
                    col2_steps.append('')
                
                # Create table data
                table_data = []
                step_counter = 0
                for i in range(len(col1_steps)):
                    row = []
                    if col1_steps[i]:
                        step_counter += 1
                        step_text = col1_steps[i].lstrip('0123456789. ')
                        row.append(Paragraph(f"<b>{step_counter}.</b> {step_text}", body_style))
                    else:
                        row.append(Paragraph('', body_style))
                    
                    if col2_steps[i]:
                        step_counter += 1
                        step_text = col2_steps[i].lstrip('0123456789. ')
                        row.append(Paragraph(f"<b>{step_counter}.</b> {step_text}", body_style))
                    else:
                        row.append(Paragraph('', body_style))
                    
                    table_data.append(row)
                
                # Create table
                prep_steps_table = Table(table_data, colWidths=[3.5*inch, 3.5*inch])
                prep_steps_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ]))
                right_page_elements.append(prep_steps_table)
                right_page_elements.append(Spacer(1, 6))
            
            # Cooking Directions
            raw_cooking_directions = recipe.get('cooking_directions', '')
            if raw_cooking_directions:
                right_page_elements.append(Paragraph("Cooking Directions", heading_style))
                # Split by newlines first
                lines = [s.strip() for s in raw_cooking_directions.split('\n') if s.strip()]
                # Then flatten by splitting on commas to match preview behavior
                all_steps = []
                for line in lines:
                    individual_steps = [s.strip() for s in line.split(',') if s.strip()]
                    all_steps.extend(individual_steps)
                
                for step_num, step_text in enumerate(all_steps, 1):
                    # Remove any existing numbering
                    step_text = step_text.lstrip('0123456789. ')
                    right_page_elements.append(Paragraph(f"{step_num}. {step_text}", body_style))
                    right_page_elements.append(Spacer(1, 2))
                right_page_elements.append(Spacer(1, 3))
            
            # Special Instructions
            if recipe.get('special_instructions'):
                right_page_elements.append(Paragraph("Special Instructions", heading_style))
                right_page_elements.append(Paragraph(recipe['special_instructions'], body_style))
            
            # Add right page elements
            for element in right_page_elements:
                story.append(element)
            
            # No empty pages needed - each recipe naturally takes 2 pages (left + right)
            # Next recipe will start on next left page automatically
        
        # Build PDF with background color
        def add_background(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(page_color)
            canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)
            canvas.restoreState()
        
        doc.build(story, onFirstPage=add_background, onLaterPages=add_background)
        
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{recipe_book_data.get('book_title', 'recipe_book').replace(' ', '_')}.pdf"
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate-book-pdf', methods=['POST'])
def generate_book_pdf():
    """Generate PDF for regular books with headers, page numbers, and proper TOC"""
    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'ReportLab not available. Install reportlab package.'}), 500
    
    try:
        data = request.json
        book_data = data.get('data', {})
        
        # Create PDF
        buffer = BytesIO()
        
        # Determine page size from trim_size
        trim_size = book_data.get('trim_size', '6x9')
        if trim_size == '6x9':
            page_width, page_height = 6*inch, 9*inch
        elif trim_size == '5.5x8.5':
            page_width, page_height = 5.5*inch, 8.5*inch
        else:
            page_width, page_height = 6*inch, 9*inch
        
        # Get page color
        page_color_name = book_data.get('page_color', 'cream')
        page_colors = {
            'white': colors.white,
            'cream': colors.Color(1, 0.996, 0.941),
            'off-white': colors.Color(0.973, 0.973, 0.973)
        }
        page_color = page_colors.get(page_color_name, page_colors['cream'])
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=(page_width, page_height),
            leftMargin=0.75*inch,
            rightMargin=0.75*inch,
            topMargin=1*inch,  # More space for header
            bottomMargin=0.75*inch
        )
        
        # Build PDF content
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles with 1.2pt line spacing
        font_size = book_data.get('font_size', 11)
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Title'],
            fontName=FONT_FAMILY,
            fontSize=24,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=12
        )
        
        author_style = ParagraphStyle(
            'Author',
            parent=styles['Normal'],
            fontName=FONT_FAMILY,
            fontSize=16,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=30
        )
        
        chapter_title_style = ParagraphStyle(
            'ChapterTitle',
            parent=styles['Heading1'],
            fontName=FONT_FAMILY,
            fontSize=18,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=24
        )
        
        # Body style with 1.2pt line spacing (leading)
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontName=FONT_FAMILY,
            fontSize=font_size,
            leading=font_size + 1.2,  # 1.2pt line spacing
            textColor=colors.black,
            alignment=TA_JUSTIFY,
            firstLineIndent=0.3*inch
        )
        
        # TOC styles
        toc_title_style = ParagraphStyle(
            'TOCTitle',
            parent=styles['Heading1'],
            fontName=FONT_FAMILY,
            fontSize=18,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=24
        )
        
        toc_entry_style = ParagraphStyle(
            'TOCEntry',
            parent=styles['Normal'],
            fontName=FONT_FAMILY,
            fontSize=11,
            textColor=colors.black,
            alignment=TA_LEFT,
            spaceAfter=8
        )
        
        # Title page (no header/page number)
        story.append(Spacer(1, 2*inch))
        story.append(Paragraph(book_data.get('book_title', 'Untitled'), title_style))
        story.append(Paragraph(f"by {book_data.get('author_name', 'Author')}", author_style))
        if book_data.get('genre'):
            story.append(Paragraph(book_data['genre'], author_style))
        story.append(PageBreak())
        
        # Dedication (no header/page number)
        if book_data.get('dedication'):
            story.append(Spacer(1, 2*inch))
            dedication_style = ParagraphStyle(
                'Dedication',
                parent=styles['Normal'],
                fontName=FONT_FAMILY,
                fontSize=12,
                textColor=colors.black,
                alignment=TA_CENTER,
                fontStyle='italic'
            )
            story.append(Paragraph(book_data['dedication'], dedication_style))
            story.append(PageBreak())
        
        # About the Author (no header/page number)
        if book_data.get('about_author'):
            about_title_style = ParagraphStyle(
                'AboutTitle',
                parent=styles['Heading2'],
                fontName=FONT_FAMILY,
                fontSize=14,
                textColor=colors.black,
                spaceAfter=12
            )
            story.append(Paragraph("About the Author", about_title_style))
            story.append(Paragraph(book_data['about_author'], body_style))
            story.append(PageBreak())
        
        # Table of Contents with dot leaders
        story.append(Paragraph("Table of Contents", toc_title_style))
        story.append(Spacer(1, 12))
        
        # Calculate chapter starting pages
        current_page = 1  # Start numbering from first chapter
        chapter_pages = {}
        
        for i, chapter in enumerate(book_data.get('chapters', [])):
            chapter_pages[i] = current_page
            # Estimate pages for this chapter
            content = chapter.get('content', '')
            word_count = len(content.split())
            estimated_pages = max(1, (word_count + 350) // 400)
            current_page += estimated_pages
        
        # Build TOC with dot leaders
        for i, chapter in enumerate(book_data.get('chapters', [])):
            default_title = f"Chapter {chapter.get('number', i+1)}"
            chapter_title = chapter.get('title', default_title)
            page_num = str(chapter_pages[i])
            
            # Create entry with dot leader
            dots = '.' * 100  # Lots of dots, table will trim
            toc_line = f"{chapter_title} {dots} {page_num}"
            
            # Use table for proper alignment
            toc_data = [[
                Paragraph(chapter_title, toc_entry_style),
                Paragraph(page_num, toc_entry_style)
            ]]
            toc_table = Table(toc_data, colWidths=[4*inch, 0.5*inch])
            toc_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.grey, None, (2, 2)),  # Dotted line
            ]))
            story.append(toc_table)
        
        story.append(PageBreak())
        
        # Track current chapter for headers
        current_chapter_title = ""
        chapter_list = book_data.get('chapters', [])
        
        # Chapters with headers
        for chapter_idx, chapter in enumerate(chapter_list):
            default_title = f"Chapter {chapter.get('number', chapter_idx+1)}"
            current_chapter_title = chapter.get('title', default_title)
            
            # Chapter title
            story.append(Paragraph(str(chapter.get('number', '')), chapter_title_style))
            story.append(Paragraph(current_chapter_title, chapter_title_style))
            story.append(Spacer(1, 24))
            
            # Chapter content
            content = chapter.get('content', '')
            paragraphs = content.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    story.append(Paragraph(para.strip(), body_style))
                    story.append(Spacer(1, 12))
            
            story.append(PageBreak())
        
        # Build PDF with background, headers, and page numbers
        front_matter_pages = 1  # title
        if book_data.get('dedication'):
            front_matter_pages += 1
        if book_data.get('about_author'):
            front_matter_pages += 1
        front_matter_pages += 1  # TOC
        
        # Track chapter titles for headers
        chapter_title_tracker = {'current': book_data.get('book_title', '')}
        
        def add_page_elements(canvas, doc):
            canvas.saveState()
            
            # Background color
            canvas.setFillColor(page_color)
            canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)
            
            # Only add headers/page numbers after front matter
            if doc.page > front_matter_pages:
                canvas.setFillColor(colors.black)
                
                # Page number (actual page - front matter pages)
                page_num = doc.page - front_matter_pages
                
                # Page numbers in 10pt font
                canvas.setFont(FONT_FAMILY, 10)
                
                # Alternate left/right for page numbers
                if page_num % 2 == 0:  # Even pages - page number on left
                    canvas.drawString(0.75*inch, page_height - 0.5*inch, str(page_num))
                else:  # Odd pages - page number on right
                    canvas.drawRightString(page_width - 0.75*inch, page_height - 0.5*inch, str(page_num))
                
                # Chapter title in center with 6.5pt font and wrapping
                canvas.setFont(FONT_FAMILY, 6.5)
                
                # Get current chapter title
                header_text = chapter_title_tracker['current']
                
                # Calculate available width for center text (between margins and page numbers)
                available_width = page_width - 2.5*inch  # Leave space for page numbers
                
                # Simple text wrapping for long titles
                from reportlab.pdfbase.pdfmetrics import stringWidth
                if stringWidth(header_text, FONT_FAMILY, 6.5) > available_width:
                    # Wrap text - split into words and fit
                    words = header_text.split()
                    lines = []
                    current_line = []
                    
                    for word in words:
                        test_line = ' '.join(current_line + [word])
                        if stringWidth(test_line, FONT_FAMILY, 6.5) <= available_width:
                            current_line.append(word)
                        else:
                            if current_line:
                                lines.append(' '.join(current_line))
                            current_line = [word]
                    
                    if current_line:
                        lines.append(' '.join(current_line))
                    
                    # Draw wrapped lines (max 2 lines)
                    y_pos = page_height - 0.5*inch
                    for i, line in enumerate(lines[:2]):
                        canvas.drawCentredString(page_width / 2, y_pos - (i * 8), line)
                else:
                    # Single line
                    canvas.drawCentredString(page_width / 2, page_height - 0.5*inch, header_text)
            
            canvas.restoreState()
        
        doc.build(story, onFirstPage=add_page_elements, onLaterPages=add_page_elements)
        
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{book_data.get('book_title', 'book').replace(' ', '_')}.pdf"
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate-childrens-book-pdf', methods=['POST'])
def generate_childrens_book_pdf():
    """Generate PDF for children's books with 8.5x11 pages"""
    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'ReportLab not available. Install reportlab package.'}), 500
    
    try:
        data = request.json
        book_data = data.get('data', {})
        
        # Create PDF
        buffer = BytesIO()
        
        # 8.5 x 11 inches
        page_width, page_height = 8.5*inch, 11*inch
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=(page_width, page_height),
            leftMargin=0.5*inch,
            rightMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )
        
        story = []
        styles = getSampleStyleSheet()
        
        # Custom Bembo style for text overlay
        text_style = ParagraphStyle(
            'ChildrenText',
            parent=styles['Normal'],
            fontName=FONT_FAMILY,
            fontSize=16,
            leading=24,
            textColor=colors.black,
            alignment=TA_CENTER,
            spaceAfter=12
        )
        
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Title'],
            fontName=FONT_FAMILY,
            fontSize=32,
            textColor=colors.black,
            alignment=TA_CENTER
        )
        
        # Title page
        story.append(Spacer(1, 3*inch))
        story.append(Paragraph(book_data.get('title', 'Untitled'), title_style))
        if book_data.get('author_name'):
            author_style = ParagraphStyle(
                'Author',
                parent=styles['Normal'],
                fontName=FONT_FAMILY,
                fontSize=18,
                textColor=colors.black,
                alignment=TA_CENTER
            )
            story.append(Spacer(1, 0.5*inch))
            story.append(Paragraph(f"by {book_data['author_name']}", author_style))
        story.append(PageBreak())
        
        # Pages with illustrations
        for page in book_data.get('pages', []):
            # Download illustration if available
            if page.get('image_url'):
                try:
                    # Handle both local and remote URLs
                    img_url = page['image_url']
                    if not img_url.startswith('http'):
                        # Assuming the image is available via the API endpoint
                        continue  # Skip if we can't access the image
                    
                    img_response = requests.get(img_url, timeout=10)
                    img_buffer = BytesIO(img_response.content)
                    
                    # Add full-page image
                    img = Image(img_buffer, width=7.5*inch, height=10*inch)
                    story.append(img)
                    
                except Exception as img_error:
                    print(f"Failed to load image: {img_error}")
            
            # Add text overlay based on position
            if page.get('text'):
                text_position = page.get('text_position', 'middle')
                
                # Calculate vertical position based on text_position
                if text_position == 'top':
                    story.append(Spacer(1, -9*inch))  # Move to top
                elif text_position == 'bottom':
                    story.append(Spacer(1, -3*inch))  # Move to bottom
                else:  # middle
                    story.append(Spacer(1, -6*inch))  # Move to middle
                
                # Create semi-transparent white background for text
                # (Note: This is simplified - in production you'd use a more sophisticated approach)
                story.append(Paragraph(page['text'], text_style))
            
            story.append(PageBreak())
        
        doc.build(story)
        
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{book_data.get('title', 'book').replace(' ', '_')}.pdf"
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate-greeting-card-pdf', methods=['POST'])
def generate_greeting_card_pdf():
    """Generate PDF for greeting cards with two-page fold layout"""
    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'ReportLab not available. Install reportlab package.'}), 500
    
    try:
        data = request.json
        card_data = data.get('data', {})
        
        # Create PDF
        buffer = BytesIO()
        
        # 10 x 7 inches landscape (folds to 5x7)
        page_width, page_height = 10*inch, 7*inch
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=(page_width, page_height),
            leftMargin=0,
            rightMargin=0,
            topMargin=0,
            bottomMargin=0
        )
        
        story = []
        styles = getSampleStyleSheet()
        
        # Get image URLs
        front_art_url = None
        inside_icon_url = None
        for brief in card_data.get('image_briefs', []):
            if brief['id'] == 'FRONT_ART':
                front_art_url = brief.get('image_url')
            elif brief['id'] == 'INSIDE_ICON':
                inside_icon_url = brief.get('image_url')
        
        # === PAGE 1: OUTSIDE (Back | Front) ===
        # Left panel: BACK
        back_logo = card_data.get('back', {}).get('logo_text', 'QuillWorks.AI')
        back_footer = card_data.get('back', {}).get('footer_line', 'Crafted with care')
        
        back_style = ParagraphStyle(
            'BackStyle',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#999999'),
        )
        
        back_para = Paragraph(f"<b>{back_logo}</b><br/><br/><font size='8'>{back_footer}</font>", back_style)
        
        # Right panel: FRONT
        front_headline = card_data.get('front', {}).get('headline', '')
        front_subline = card_data.get('front', {}).get('subline', '')
        
        front_elements = []
        
        # Add front art if available
        if front_art_url and front_art_url.startswith('http'):
            try:
                img_response = requests.get(front_art_url, timeout=10)
                img_buffer = BytesIO(img_response.content)
                front_img = Image(img_buffer, width=4.5*inch, height=5*inch)
                front_elements.append(front_img)
            except Exception as e:
                print(f"Failed to load front art: {e}")
        
        front_elements.append(Spacer(1, 0.3*inch))
        
        # Front text
        front_title_style = ParagraphStyle(
            'FrontTitle',
            parent=styles['Heading1'],
            fontSize=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=6,
        )
        
        front_sub_style = ParagraphStyle(
            'FrontSub',
            parent=styles['Normal'],
            fontSize=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#34495e'),
            fontStyle='italic',
        )
        
        front_elements.append(Paragraph(f"<b>{front_headline}</b>", front_title_style))
        if front_subline:
            front_elements.append(Paragraph(front_subline, front_sub_style))
        
        # Create table for outside
        outside_data = [[back_para, front_elements]]
        outside_table = Table(outside_data, colWidths=[5*inch, 5*inch], rowHeights=[7*inch])
        outside_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#f8f9fa')),
            ('BACKGROUND', (1, 0), (1, 0), colors.white),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
        ]))
        
        story.append(outside_table)
        story.append(PageBreak())
        
        # === PAGE 2: INSIDE (Left | Right) ===
        # Left panel: INSIDE_LEFT (quote/verse)
        inside_left_msg = card_data.get('inside_left', {}).get('message', '')
        
        quote_style = ParagraphStyle(
            'QuoteStyle',
            parent=styles['Normal'],
            fontSize=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#7f8c8d'),
            fontStyle='italic',
            leading=16,
        )
        
        left_para = Paragraph(inside_left_msg, quote_style) if inside_left_msg else Spacer(1, 1*inch)
        
        # Right panel: INSIDE_RIGHT (main message)
        inside_right_msg = card_data.get('inside_right', {}).get('message', '')
        
        right_elements = []
        
        # Add decorative icon if available
        if inside_icon_url and inside_icon_url.startswith('http'):
            try:
                img_response = requests.get(inside_icon_url, timeout=10)
                img_buffer = BytesIO(img_response.content)
                icon_img = Image(img_buffer, width=1*inch, height=1*inch)
                right_elements.append(icon_img)
                right_elements.append(Spacer(1, 0.2*inch))
            except Exception as e:
                print(f"Failed to load inside icon: {e}")
        
        message_style = ParagraphStyle(
            'MessageStyle',
            parent=styles['Normal'],
            fontSize=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#2c3e50'),
            leading=18,
        )
        
        right_elements.append(Paragraph(inside_right_msg, message_style))
        
        # Create table for inside
        inside_data = [[left_para, right_elements]]
        inside_table = Table(inside_data, colWidths=[5*inch, 5*inch], rowHeights=[7*inch])
        inside_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('LEFTPADDING', (0, 0), (-1, -1), 30),
            ('RIGHTPADDING', (0, 0), (-1, -1), 30),
        ]))
        
        story.append(inside_table)
        
        # Build PDF
        doc.build(story)
        
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{card_data.get('occasion', 'greeting_card').replace(' ', '_')}.pdf"
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate-book-docx', methods=['POST'])
def generate_book_docx_endpoint():
    """Generate DOCX for regular books"""
    if not DOCX_AVAILABLE:
        return jsonify({'error': 'DOCX generation not available'}), 500
    
    try:
        data = request.json
        book_data = data.get('data', {})
        
        # Generate DOCX
        docx_bytes = generate_book_docx(book_data)
        
        buffer = BytesIO(docx_bytes)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=f"{book_data.get('book_title', 'book').replace(' ', '_')}.docx"
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Remove Background Endpoint ---


@app.route('/deploy-pages', methods=['POST'])
def deploy_pages():
    """
    Build and deploy a project to Cloudflare Pages using Wrangler CLI.
    """
    temp_dir = None
    try:
        data = request.json
        project_name = data.get('project_name')
        subdomain = data.get('subdomain')
        files = data.get('files', [])
        cf_account_id = data.get('cf_account_id')
        cf_api_token = data.get('cf_api_token')
        cf_zone_id = data.get('cf_zone_id')
        environment = data.get('environment', 'prod')  # 'dev' or 'prod'
        custom_domain_override = data.get('custom_domain')  # Optional: user's custom domain (e.g., myapp.com)
        
        if not project_name or not subdomain or not files:
            return jsonify({'error': 'Missing required fields: project_name, subdomain, files'}), 400
        
        # Ensure subdomain format matches environment:
        # - Dev: should have "dev-" prefix (e.g., "dev-vibe-123")
        # - Prod: should NOT have "dev-" prefix (e.g., "vibe-123")
        if environment == "dev":
            if not subdomain.startswith("dev-"):
                # Add "dev-" prefix if missing
                original_subdomain = subdomain
                subdomain = f"dev-{subdomain}"
                print(f"[Pages] Added 'dev-' prefix to subdomain: {original_subdomain} -> {subdomain}")
            # Ensure project_name also has "dev-" prefix for consistency
            if not project_name.startswith("dev-"):
                project_name = f"dev-{project_name}"
                print(f"[Pages] Added 'dev-' prefix to project_name: {project_name}")
        else:  # prod
            if subdomain.startswith("dev-"):
                # Remove "dev-" prefix for prod
                original_subdomain = subdomain
                subdomain = subdomain.replace("dev-", "", 1)
                print(f"[Pages] Removed 'dev-' prefix from subdomain: {original_subdomain} -> {subdomain}")
            # Ensure project_name doesn't have "dev-" prefix for prod
            if project_name.startswith("dev-"):
                project_name = project_name.replace("dev-", "", 1)
                print(f"[Pages] Removed 'dev-' prefix from project_name: {project_name}")
        
        # Validate that subdomain matches project_name pattern (after prefix adjustments)
        if subdomain != project_name:
            return jsonify({
                'error': f'Subdomain "{subdomain}" must match project_name "{project_name}" for consistency'
            }), 400
        
        # Validate subdomain format (alphanumeric, hyphens, underscores only, no spaces)
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', subdomain):
            return jsonify({
                'error': 'Subdomain must contain only alphanumeric characters, hyphens, and underscores'
            }), 400
        
        # Only require credentials for Wrangler CLI, not for direct API calls
        if not (cf_api_token or os.environ.get("CLOUDFLARE_API_TOKEN")) or not (cf_account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")):
            return jsonify({'error': 'Missing Cloudflare credentials for Wrangler CLI. Provide cf_account_id and cf_api_token in request or set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN environment variables'}), 400
        
        # Create temp directory for project files
        temp_dir = tempfile.mkdtemp(prefix=f"pages-{project_name}-")
        print(f"[Pages] Created temp dir: {temp_dir}")
        
        # Write all files to temp directory
        for file in files:
            file_path = os.path.join(temp_dir, file.get('path', ''))
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file.get('content', ''))
        
        print(f"[Pages] Wrote {len(files)} files")
        
        # Set environment variables for Wrangler and DNS creation
        env = os.environ.copy()
        env["CLOUDFLARE_API_TOKEN"] = os.environ.get("CLOUDFLARE_API_TOKEN") or cf_api_token
        env["CLOUDFLARE_ACCOUNT_ID"] = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or cf_account_id
        env["CLOUDFLARE_ZONE_ID"] = os.environ.get("CLOUDFLARE_ZONE_ID") or cf_zone_id or ""
        
        # Create wrangler.toml file for Wrangler CLI authentication
        wrangler_toml_path = os.path.join(temp_dir, "wrangler.toml")
        with open(wrangler_toml_path, 'w') as f:
            f.write(f"""# Wrangler configuration for Cloudflare Pages deployment
    # This file is auto-generated for deployment

    account_id = "{cf_account_id or os.environ.get('CLOUDFLARE_ACCOUNT_ID')}"

    # Pages projects don't need a name in wrangler.toml, but account_id is required
    """)
        print(f"[Pages] ✅ Created wrangler.toml with account_id for authentication")
        
        # Detect framework and build
        package_json_path = os.path.join(temp_dir, "package.json")
        output_dir = "dist"
        is_react_app = False
        
        if os.path.exists(package_json_path):
            with open(package_json_path) as f:
                pkg = json.load(f)
            
            # Fix build script: Remove --verbose flag if present (Vite doesn't support it)
            if "scripts" in pkg and "build" in pkg["scripts"]:
                build_script = pkg["scripts"]["build"]
                if "--verbose" in build_script:
                    # Remove --verbose flag
                    pkg["scripts"]["build"] = build_script.replace("--verbose", "").strip()
                    # Write back the fixed package.json
                    with open(package_json_path, 'w') as f:
                        json.dump(pkg, f, indent=2)
                    print(f"[Pages] ✅ Removed --verbose from build script (Vite doesn't support it)")
                    print(f"[Pages] Build script: {pkg['scripts']['build']}")
            
            # Fix TypeScript configuration: Ensure module and moduleResolution match
            tsconfig_path = os.path.join(temp_dir, "tsconfig.json")
            if os.path.exists(tsconfig_path):
                try:
                    with open(tsconfig_path, 'r', encoding='utf-8') as f:
                        tsconfig = json.load(f)
                    
                    compiler_options = tsconfig.get("compilerOptions", {})
                    module_resolution = compiler_options.get("moduleResolution")
                    module = compiler_options.get("module")
                    
                    # Fix: If moduleResolution is NodeNext, module must also be NodeNext
                    if module_resolution == "NodeNext" and module != "NodeNext":
                        compiler_options["module"] = "NodeNext"
                        tsconfig["compilerOptions"] = compiler_options
                        with open(tsconfig_path, 'w', encoding='utf-8') as f:
                            json.dump(tsconfig, f, indent=2)
                        print(f"[Pages] ✅ Fixed TypeScript config: set module to 'NodeNext' to match moduleResolution")
                except Exception as tsconfig_err:
                    print(f"[Pages] ⚠️ Could not fix tsconfig.json: {tsconfig_err}")
            
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            
            # Detect output directory
            if "next" in deps:
                output_dir = "out"  # Next.js static export
            elif "vite" in deps or "react" in deps:
                output_dir = "dist"
                is_react_app = True
            
            # Create _redirects file for React/Vite apps (for client-side routing)
            # For Vite, put it in public/ so it gets copied to build output
            if is_react_app:
                # Check if _redirects already exists in files
                has_redirects = any(f.get('path', '').endswith('_redirects') or 
                                   f.get('path', '').endswith('public/_redirects') for f in files)
                
                if not has_redirects:
                    # Create _redirects file in public folder (Vite/CRA standard)
                    public_dir = os.path.join(temp_dir, "public")
                    os.makedirs(public_dir, exist_ok=True)
                    redirects_path = os.path.join(public_dir, "_redirects")
                    
                    # Cloudflare Pages redirect rule: all routes -> index.html with 200 status
                    with open(redirects_path, 'w', encoding='utf-8') as f:
                        f.write("/*    /index.html   200\n")
                    print(f"[Pages] ✅ Created _redirects file in public/ for client-side routing")
            else:
                # For non-React apps, create in root
                redirects_path = os.path.join(temp_dir, "_redirects")
                if not os.path.exists(redirects_path):
                    with open(redirects_path, 'w', encoding='utf-8') as f:
                        f.write("/*    /index.html   200\n")
                    print(f"[Pages] ✅ Created _redirects file for client-side routing")
            
            # Install dependencies
            print(f"[Pages] Running npm install...")
            result = subprocess.run(
                ["npm", "install", "--legacy-peer-deps"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                env=env,
                timeout=300  # 5 min timeout
            )
            if result.returncode != 0:
                error_output = result.stderr or result.stdout or "No error output available"
                print(f"[Pages] npm install failed with return code: {result.returncode}")
                print(f"[Pages] npm install stderr: {result.stderr[:1000] if result.stderr else '(empty)'}")
                print(f"[Pages] npm install stdout: {result.stdout[:1000] if result.stdout else '(empty)'}")
                return jsonify({
                    'error': f'npm install failed: {error_output[:500]}',
                    'details': {
                        'exit_code': result.returncode,
                        'stderr': result.stderr[:1000] if result.stderr else None,
                        'stdout': result.stdout[:1000] if result.stdout else None
                    }
                }), 500
            
            # Run build with retry logic for fixable errors
            print(f"[Pages] Running npm run build in {temp_dir}...", flush=True)
            print(f"[Pages] Working directory contents: {os.listdir(temp_dir)[:10]}", flush=True)
            print(f"[Pages] Build script: {pkg['scripts'].get('build', 'N/A')}", flush=True)  # Log the actual script
            
            build_retry_count = 0
            max_build_retries = 2  # Allow one retry after fixing config
            build_success = False
            
            while build_retry_count <= max_build_retries and not build_success:
                if build_retry_count > 0:
                    print(f"[Pages] Retrying build (attempt {build_retry_count + 1}/{max_build_retries + 1})...", flush=True)
                
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=300
                )
                
                if result.returncode == 0:
                    print(f"[Pages] ✅ Build completed successfully", flush=True)
                    build_success = True
                    break
                else:
                    error_output = result.stderr or result.stdout or "No error output available"
                    print(f"[Pages] Build failed (exit code {result.returncode})", flush=True)
                    print(f"[Pages] Build stderr: {result.stderr[:1000] if result.stderr else '(empty)'}", flush=True)
                    print(f"[Pages] Build stdout: {result.stdout[:1000] if result.stdout else '(empty)'}", flush=True)
                    
                    # Check for missing npm packages and try to install them
                    missing_packages = []
                    if "Cannot find module" in error_output or "TS2307" in error_output:
                        import re
                        # Extract module names from error messages like "Cannot find module '@react-pdf/renderer'"
                        module_pattern = r"Cannot find module ['\"]([^'\"]+)['\"]"
                        matches = re.findall(module_pattern, error_output)
                        missing_packages.extend(matches)
                        
                        # Also check for TS2307 errors
                        ts2307_pattern = r"TS2307.*module ['\"]([^'\"]+)['\"]"
                        ts_matches = re.findall(ts2307_pattern, error_output)
                        missing_packages.extend(ts_matches)
                        
                        if missing_packages:
                            # Remove duplicates and @types packages (install the main package)
                            missing_packages = list(set([pkg for pkg in missing_packages if not pkg.startswith('@types/')]))
                            if missing_packages:
                                print(f"[Pages] Detected missing packages: {missing_packages}", flush=True)
                                
                                # Check which packages are actually missing from package.json
                                existing_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                                packages_to_add = [pkg for pkg in missing_packages if pkg not in existing_deps]
                                
                                if packages_to_add:
                                    print(f"[Pages] Adding missing packages to package.json: {packages_to_add}", flush=True)
                                    
                                    # Determine which packages go to dependencies vs devDependencies
                                    # Build-time packages (types, build tools) go to devDependencies
                                    # Runtime packages go to dependencies
                                    dev_dep_keywords = ['@types/', 'typescript', 'ts-', 'eslint', 'prettier', 'vite', 'webpack', 'rollup', 'babel']
                                    runtime_packages = []
                                    dev_packages = []
                                    
                                    for pkg_name in packages_to_add:
                                        # Check if it's a dev dependency (build tool, type definitions, etc.)
                                        is_dev_dep = any(keyword in pkg_name.lower() for keyword in dev_dep_keywords)
                                        if is_dev_dep:
                                            dev_packages.append(pkg_name)
                                        else:
                                            runtime_packages.append(pkg_name)
                                    
                                    # Add runtime packages to dependencies
                                    if runtime_packages:
                                        if "dependencies" not in pkg:
                                            pkg["dependencies"] = {}
                                        for pkg_name in runtime_packages:
                                            pkg["dependencies"][pkg_name] = "latest"
                                        print(f"[Pages] Adding to dependencies: {runtime_packages}", flush=True)
                                    
                                    # Add build-time packages to devDependencies
                                    if dev_packages:
                                        if "devDependencies" not in pkg:
                                            pkg["devDependencies"] = {}
                                        for pkg_name in dev_packages:
                                            pkg["devDependencies"][pkg_name] = "latest"
                                        print(f"[Pages] Adding to devDependencies: {dev_packages}", flush=True)
                                    
                                    # Write updated package.json
                                    with open(package_json_path, 'w', encoding='utf-8') as f:
                                        json.dump(pkg, f, indent=2)
                                    print(f"[Pages] ✅ Updated package.json with missing packages", flush=True)
                                
                                # Install all missing packages (including ones that might be in package.json but not installed)
                                print(f"[Pages] Installing missing packages: {missing_packages}", flush=True)
                                install_result = subprocess.run(
                                    ["npm", "install", "--legacy-peer-deps"] + missing_packages,
                                    cwd=temp_dir,
                                    capture_output=True,
                                    text=True,
                                    env=env,
                                    timeout=180
                                )
                                if install_result.returncode == 0:
                                    print(f"[Pages] ✅ Installed missing packages: {', '.join(missing_packages)}", flush=True)
                                    # Update package.json with actual installed versions from package-lock.json
                                    package_lock_path = os.path.join(temp_dir, "package-lock.json")
                                    if os.path.exists(package_lock_path):
                                        try:
                                            with open(package_lock_path, 'r', encoding='utf-8') as f:
                                                package_lock = json.load(f)
                                            # Update versions in package.json from package-lock.json
                                            if "packages" in package_lock:
                                                for pkg_name in packages_to_add:
                                                    pkg_key = f"node_modules/{pkg_name}" if not pkg_name.startswith("@") else f"node_modules/{pkg_name.replace('/', '/')}"
                                                    if pkg_key in package_lock.get("packages", {}):
                                                        installed_version = package_lock["packages"][pkg_key].get("version", "latest")
                                                        # Update in the correct section (dependencies or devDependencies)
                                                        if pkg_name in pkg.get("dependencies", {}):
                                                            pkg["dependencies"][pkg_name] = installed_version
                                                        elif pkg_name in pkg.get("devDependencies", {}):
                                                            pkg["devDependencies"][pkg_name] = installed_version
                                                # Write back with actual versions
                                                with open(package_json_path, 'w', encoding='utf-8') as f:
                                                    json.dump(pkg, f, indent=2)
                                                print(f"[Pages] ✅ Updated package.json with installed versions", flush=True)
                                        except Exception as lock_err:
                                            print(f"[Pages] ⚠️ Could not update versions from package-lock.json: {lock_err}", flush=True)
                                    
                                    build_retry_count += 1
                                    continue  # Retry build
                                else:
                                    print(f"[Pages] ⚠️ Failed to install missing packages: {install_result.stderr[:500]}", flush=True)
                            else:
                                print(f"[Pages] All missing packages are already in package.json, but build still fails", flush=True)
                                print(f"[Pages] This might indicate a different issue (version conflict, peer dependency, etc.)", flush=True)
                    
                    # Check for TypeScript implicit 'any' errors and relax strictness
                    if "TS7031" in error_output and "implicitly has an 'any' type" in error_output:
                        print(f"[Pages] Detected TypeScript implicit 'any' errors, attempting to relax strictness...", flush=True)
                        tsconfig_path = os.path.join(temp_dir, "tsconfig.json")
                        if os.path.exists(tsconfig_path):
                            try:
                                with open(tsconfig_path, 'r', encoding='utf-8') as f:
                                    tsconfig = json.load(f)
                                
                                compiler_options = tsconfig.get("compilerOptions", {})
                                # Disable noImplicitAny to allow implicit any types
                                compiler_options["noImplicitAny"] = False
                                tsconfig["compilerOptions"] = compiler_options
                                with open(tsconfig_path, 'w', encoding='utf-8') as f:
                                    json.dump(tsconfig, f, indent=2)
                                print(f"[Pages] ✅ Relaxed TypeScript strictness: disabled noImplicitAny", flush=True)
                                build_retry_count += 1
                                continue  # Retry build
                            except Exception as tsconfig_err:
                                print(f"[Pages] ⚠️ Could not fix tsconfig.json: {tsconfig_err}", flush=True)
                    
                    # Check for TypeScript configuration error and fix it
                    if "TS5110" in error_output and "module" in error_output and "moduleResolution" in error_output:
                        print(f"[Pages] Detected TypeScript config error (TS5110), attempting to fix...", flush=True)
                        tsconfig_path = os.path.join(temp_dir, "tsconfig.json")
                        if os.path.exists(tsconfig_path):
                            try:
                                with open(tsconfig_path, 'r', encoding='utf-8') as f:
                                    tsconfig = json.load(f)
                                
                                compiler_options = tsconfig.get("compilerOptions", {})
                                module_resolution = compiler_options.get("moduleResolution")
                                
                                # Fix: If moduleResolution is NodeNext, module must also be NodeNext
                                if module_resolution == "NodeNext":
                                    compiler_options["module"] = "NodeNext"
                                    tsconfig["compilerOptions"] = compiler_options
                                    with open(tsconfig_path, 'w', encoding='utf-8') as f:
                                        json.dump(tsconfig, f, indent=2)
                                    print(f"[Pages] ✅ Fixed TypeScript config: set module to 'NodeNext'", flush=True)
                                    build_retry_count += 1
                                    continue  # Retry build
                            except Exception as tsconfig_err:
                                print(f"[Pages] ⚠️ Could not fix tsconfig.json: {tsconfig_err}", flush=True)
                    
                    # If we can't fix it or max retries reached, return error
                    if build_retry_count >= max_build_retries:
                        return jsonify({
                            'error': f'Build failed: {error_output[:500]}',
                            'details': {
                                'exit_code': result.returncode,
                                'stderr': result.stderr[:1000] if result.stderr else None,
                                'stdout': result.stdout[:1000] if result.stdout else None
                            },
                            'build_script': pkg['scripts'].get('build', 'N/A')
                        }), 500
                    else:
                        build_retry_count += 1
        
        # Check if output directory exists
        build_path = os.path.join(temp_dir, output_dir)
        if not os.path.exists(build_path):
            # Fall back to current directory if build output doesn't exist
            print(f"[Pages] ⚠️ No {output_dir} directory found after build")
            print(f"[Pages] Checking temp_dir contents: {os.listdir(temp_dir)[:10]}")
            build_path = temp_dir
            print(f"[Pages] Using project root as build path: {build_path}")
        else:
            print(f"[Pages] ✅ Build output found at: {build_path}")
            print(f"[Pages] Build output contents: {os.listdir(build_path)[:10]}")
        
        # Ensure _redirects file is in build output for React/Vite apps
        if is_react_app:
            redirects_in_build = os.path.join(build_path, "_redirects")
            redirects_in_public = os.path.join(temp_dir, "public", "_redirects")
            
            # Copy _redirects to build output if it doesn't exist there
            if not os.path.exists(redirects_in_build):
                if os.path.exists(redirects_in_public):
                    shutil.copy2(redirects_in_public, redirects_in_build)
                    print(f"[Pages] ✅ Copied _redirects from public/ to build output")
                else:
                    # Create it directly in build output as fallback
                    with open(redirects_in_build, 'w', encoding='utf-8') as f:
                        f.write("/*    /index.html   200\n")
                    print(f"[Pages] ✅ Created _redirects in build output")
            else:
                print(f"[Pages] ✅ _redirects file found in build output")
        
        # Only use Wrangler CLI for project creation and deployment. No direct Cloudflare API calls remain.
        print(f"[Pages] Creating/verifying Cloudflare Pages project: {project_name}")
        print(f"[Pages] Production branch: main (preview branch will create preview environment automatically)")
        result = subprocess.run(
            [
                "npx", "--yes", "wrangler@latest", "pages", "project", "create", project_name,
                "--production-branch", "main"
            ],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )
        print(f"[Pages] Project create exit code: {result.returncode}", flush=True)
        if result.stdout:
            print(f"[Pages] Project create stdout (first 1000 chars): {result.stdout[:1000]}", flush=True)
            if len(result.stdout) > 1000:
                print(f"[Pages] ... (stdout truncated, total length: {len(result.stdout)})", flush=True)
        if result.stderr:
            print(f"[Pages] Project create stderr (first 1000 chars): {result.stderr[:1000]}", flush=True)
            if len(result.stderr) > 1000:
                print(f"[Pages] ... (stderr truncated, total length: {len(result.stderr)})", flush=True)
        if result.returncode == 0:
            print(f"[Pages] ✅ Cloudflare Pages project created: {project_name}")
            print(f"[Pages] Note: Preview environment will be created automatically when deploying to 'preview' branch")
        else:
            # Check for "already exists" - this is actually success (project already created)
            error_output_lower = (result.stderr or result.stdout or "").lower()
            if any(phrase in error_output_lower for phrase in [
                "already exists", "already exists", "already configured", "is already",
                "duplicate", "conflict", "name is already taken"
            ]):
                print(f"[Pages] ✅ Cloudflare Pages project already exists: {project_name} (that's OK)")
                print(f"[Pages] Will deploy to {'preview' if environment == 'dev' else 'main'} branch")
            else:
                print(f"[Pages] ⚠️ Project creation failed. See output above.")
                # Continue anyway - deployment might still work if project exists
        
        # Deploy to Cloudflare Pages using Wrangler with retry logic
        # For dev: Creates/updates dev-vibe-*.quillworks.org (Preview Environment, preview branch) - shown in iframe
        # For prod: Creates/updates vibe-*.quillworks.org (Production Environment, main branch) - opened via "View Live App"
        branch_used = "preview" if environment == "dev" else "main"
        print(f"[Pages] Deploying to Cloudflare Pages ({environment} environment, {branch_used} branch): {project_name}")
        print(f"[Pages] Custom domain: {subdomain}.quillworks.org")
        max_retries = 3
        retry_delay = 5  # seconds
        deployment_url = None
        stable_url = None  # Stable project URL without deployment hash
        
        for attempt in range(max_retries):
            if attempt > 0:
                print(f"[Pages] Retry attempt {attempt + 1}/{max_retries} after {retry_delay}s delay...")
                import time
                time.sleep(retry_delay)
            
            # Use Cloudflare Pages Preview Environment for dev, Production for prod
            # Preview deployments: Use "preview" branch (creates preview environment automatically)
            # Production deployments: Use "main" branch (production environment)
            deployment_branch = "preview" if environment == "dev" else "main"
            print(f"[Pages] Deploying to {environment} environment using branch: {deployment_branch}")
            
            # NOTE: Authentication handled via CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN env vars
            result = subprocess.run(
                [
                    "npx", "wrangler", "pages", "deploy", build_path,
                    "--project-name", project_name,
                    "--branch", deployment_branch,
                    "--commit-dirty=true"
                ],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                env=env,
                timeout=300
            )
            
            if result.returncode == 0:
                # Success - parse deployment URL
                # Wrangler returns: "✨ Deployment complete! Visit: https://0da3x230.dev-vibe-176mvke.pages.dev"
                # Extract the full URL including any deployment hash
                for line in result.stdout.split('\n'):
                    if 'https://' in line and '.pages.dev' in line:
                        # Extract URL from line (handles various formats)
                        url_start = line.find('https://')
                        if url_start >= 0:
                            url_end = line.find(' ', url_start)
                            if url_end == -1:
                                url_end = len(line)
                            deployment_url = line[url_start:url_end].strip()
                            break

                if deployment_url:
                    print(f"[Pages] ✅ Deployed successfully to {environment} environment: {deployment_url}")
                    
                    # Extract stable project URL (without deployment hash)
                    # Preview: https://{hash}.preview.{project}.pages.dev → https://preview.{project}.pages.dev
                    # Production: https://{hash}.{project}.pages.dev → https://{project}.pages.dev (remove dev- prefix)
                    stable_url = deployment_url
                    if '.pages.dev' in deployment_url:
                        url_without_protocol = deployment_url.replace('https://', '')
                        parts = url_without_protocol.split('.')
                        
                        # Check if this is a preview deployment (has "preview" subdomain)
                        # Format: {hash}.preview.{project}.pages.dev
                        if 'preview' in parts and len(parts) >= 4:
                            # Find the preview subdomain
                            preview_idx = parts.index('preview')
                            if preview_idx > 0:  # There's a hash before preview
                                # Check if first part is a hash (8-10 chars, alphanumeric)
                                if len(parts[0]) <= 10 and parts[0].replace('-', '').isalnum():
                                    # Remove hash, keep preview and everything after
                                    # Example: ['029820d1', 'preview', 'dev-vibe-177ai54uy', 'pages', 'dev']
                                    # Result: ['preview', 'dev-vibe-177ai54uy', 'pages', 'dev']
                                    stable_url = f"https://{'.'.join(parts[1:])}"
                                    print(f"[Pages] 📌 Stable preview URL (no hash): {stable_url}")
                        else:
                            # Production deployment: {hash}.{project}.pages.dev
                            if len(parts) >= 3 and len(parts[0]) <= 10 and parts[0].replace('-', '').isalnum():
                                # Remove hash
                                project_with_dev_prefix = '.'.join(parts[1:])
                                # For production, also remove dev- prefix from project name
                                # Example: dev-vibe-177ai54uy.pages.dev → vibe-177ai54uy.pages.dev
                                if environment == "prod" and parts[1].startswith('dev-'):
                                    # Remove dev- prefix for production stable URL
                                    project_without_dev = parts[1].replace('dev-', '', 1)
                                    stable_url = f"https://{project_without_dev}.{'.'.join(parts[2:])}"
                                    print(f"[Pages] 📌 Stable production URL (no hash, no dev- prefix): {stable_url}")
                                else:
                                    stable_url = f"https://{project_with_dev_prefix}"
                                    print(f"[Pages] 📌 Stable project URL (no hash): {stable_url}")
                    
                    if environment == "dev":
                        print(f"[Pages] Preview environment created/updated at: {deployment_url}")
                        print(f"[Pages] This is the preview environment (preview branch) - shown in iframe for coding")
                        if stable_url != deployment_url:
                            print(f"[Pages] 💡 Stable preview URL (always points to latest preview): {stable_url}")
                    else:
                        print(f"[Pages] Production environment deployed at: {deployment_url}")
                        print(f"[Pages] This is the production environment (main branch) - opened via 'View Live App'")
                        if stable_url != deployment_url:
                            print(f"[Pages] 💡 Stable production URL (always points to latest): {stable_url}")
                else:
                    print(f"[Pages] ⚠️ Deployment succeeded but couldn't parse deployment URL from output")
                    print(f"[Pages] Full output: {result.stdout[:500]}")
                
                break
            else:
                error_msg = result.stderr or result.stdout or ""
                print(f"[Pages] Deploy attempt {attempt + 1} failed: {error_msg[:500]}")
                
                # Check if it's a retryable error (service unavailable, rate limit, etc.)
                is_retryable = any(code in error_msg for code in ['7010', 'Service unavailable', 'rate limit', 'timeout'])
                
                if not is_retryable or attempt == max_retries - 1:
                    # Non-retryable error or last attempt
                    print(f"[Pages] ❌ Wrangler deploy failed after {attempt + 1} attempts")
                    return jsonify({
                        'error': f'Wrangler deploy failed: {error_msg[:500]}',
                        'attempts': attempt + 1,
                        'retryable': is_retryable
                    }), 500
        
        if not deployment_url:
            return jsonify({'error': 'Deployment succeeded but could not parse deployment URL'}), 500
        
        # deployment_url is now set in the retry loop above
        
        # Add/verify custom domain is attached to the Pages project
        # Dev: dev-vibe-*.quillworks.org (Preview Environment, preview branch) - for coding in iframe
        # Prod: vibe-*.quillworks.org OR user's custom domain (Production Environment, main branch) - for live app
        if custom_domain_override:
            # User provided custom domain (e.g., myapp.com)
            custom_domain = custom_domain_override
            print(f"[Pages] Using user-provided custom domain: {custom_domain}")
        else:
            # Default to .quillworks.org
            custom_domain = f"{subdomain}.quillworks.org"
            print(f"[Pages] Using default .quillworks.org domain: {custom_domain}")
        
        branch_used = "preview" if environment == "dev" else "main"
        print(f"[Pages] Environment: {environment} (branch: {branch_used})")
        print(f"[Pages] Deployment URL: {deployment_url}")
        print(f"[Pages] This {environment} deployment will be accessible at {custom_domain}")
        
        try:
            # Step 1: Create DNS CNAME record via Cloudflare API (Wrangler doesn't handle DNS)
            import requests as req
            api_token = env.get("CLOUDFLARE_API_TOKEN")
            zone_id = env.get("CLOUDFLARE_ZONE_ID")
            
            # Validate zone_id
            if zone_id and ('.' in zone_id or len(zone_id) < 20):
                print(f"[Pages] ⚠️ Warning: zone_id looks invalid (got: {zone_id}). Expected a 32-char zone ID hash.")
                zone_id = None
            
            dns_created = False
            
            # Debug: Check if env vars are set
            print(f"[Pages] DNS Setup - Checking environment variables...")
            print(f"[Pages] CLOUDFLARE_API_TOKEN present: {bool(api_token)}")
            print(f"[Pages] CLOUDFLARE_ZONE_ID present: {bool(zone_id)}")
            if api_token:
                print(f"[Pages] API Token length: {len(api_token)}")
            if zone_id:
                print(f"[Pages] Zone ID length: {len(zone_id)}")
            
            if zone_id and api_token:
                # For preview deployments, use the preview subdomain
                # Production: project-name.pages.dev
                # Preview: preview.project-name.pages.dev (stable URL for preview branch)
                if environment == "dev":
                    pages_dev_url = f"preview.{project_name}.pages.dev"
                else:
                    pages_dev_url = f"{project_name}.pages.dev"
                print(f"[Pages] Creating DNS CNAME: {custom_domain} → {pages_dev_url}")
                print(f"[Pages] Environment: {environment}, using {'preview subdomain' if environment == 'dev' else 'production URL'}")
                
                try:
                    # Check if DNS record already exists
                    check_response = req.get(
                        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
                        headers={
                            "Authorization": f"Bearer {api_token}",
                            "Content-Type": "application/json"
                        },
                        params={"name": custom_domain, "type": "CNAME"},
                        timeout=30
                    )
                    
                    if check_response.status_code == 200:
                        existing_records = check_response.json().get("result", [])
                        if existing_records and existing_records[0].get("content") == pages_dev_url:
                            print(f"[Pages] ✅ DNS CNAME already exists: {custom_domain}")
                            dns_created = True
                        elif existing_records:
                            # Update existing record
                            record_id = existing_records[0]["id"]
                            update_response = req.put(
                                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}",
                                headers={
                                    "Authorization": f"Bearer {api_token}",
                                    "Content-Type": "application/json"
                                },
                                json={
                                    "type": "CNAME",
                                    "name": subdomain,
                                    "content": pages_dev_url,
                                    "proxied": True
                                },
                                timeout=30
                            )
                            if update_response.status_code in [200, 201]:
                                print(f"[Pages] ✅ DNS CNAME updated: {custom_domain}")
                                dns_created = True
                    
                    # Create DNS record if it doesn't exist
                    if not dns_created:
                        dns_response = req.post(
                            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
                            headers={
                                "Authorization": f"Bearer {api_token}",
                                "Content-Type": "application/json"
                            },
                            json={
                                "type": "CNAME",
                                "name": subdomain,
                                "content": pages_dev_url,
                                "proxied": True,
                                "ttl": 1
                            },
                            timeout=30
                        )
                        
                        if dns_response.status_code in [200, 201]:
                            print(f"[Pages] ✅ DNS CNAME created: {custom_domain} → {pages_dev_url}")
                            dns_created = True
                        else:
                            dns_result = dns_response.json()
                            if dns_result.get("errors") and any(e.get("code") == 81057 for e in dns_result.get("errors", [])):
                                print(f"[Pages] ✅ DNS record already exists")
                                dns_created = True
                            else:
                                print(f"[Pages] ⚠️ DNS creation failed: {dns_response.status_code}")
                except Exception as dns_err:
                    print(f"[Pages] ⚠️ DNS creation error: {dns_err}")
                    import traceback
                    traceback.print_exc()
            else:
                if not zone_id:
                    print(f"[Pages] ⚠️ CLOUDFLARE_ZONE_ID not set - skipping DNS creation")
                    print(f"[Pages] ⚠️ Set CLOUDFLARE_ZONE_ID environment variable on Railway to enable automatic DNS")
                if not api_token:
                    print(f"[Pages] ⚠️ CLOUDFLARE_API_TOKEN not set - skipping DNS creation")
                    print(f"[Pages] ⚠️ Set CLOUDFLARE_API_TOKEN environment variable on Railway to enable automatic DNS")
            
            # Step 2: Add custom domain to Pages project using Wrangler CLI
            print(f"[Pages] Adding custom domain via Wrangler CLI...")
            print(f"[Pages] Custom domain: {custom_domain}")
            print(f"[Pages] Project name: {project_name}")
            
            domain_attached = False
            wrangler_cwd = os.path.expanduser("~") if os.path.exists(os.path.expanduser("~")) else temp_dir
            
            print(f"[Pages] Running: wrangler pages domain add {custom_domain} --project-name {project_name}")
            domain_result = subprocess.run(
                [
                    "npx", "--yes", "wrangler@latest", "pages", "domain", "add",
                    custom_domain,
                    "--project-name", project_name
                ],
                cwd=wrangler_cwd,
                capture_output=True,
                text=True,
                env=env,
                timeout=90
            )
            
            if domain_result.returncode == 0:
                print(f"[Pages] ✅ Custom domain added via Wrangler: {custom_domain}")
                domain_attached = True
            else:
                error_output = (domain_result.stderr or domain_result.stdout or "").lower()
                if any(phrase in error_output for phrase in ["already", "already exists", "already configured"]):
                    print(f"[Pages] ✅ Custom domain already attached (that's OK)")
                    domain_attached = True
                else:
                    print(f"[Pages] ⚠️ Wrangler failed to attach domain: {domain_result.stderr[:500] if domain_result.stderr else domain_result.stdout[:500]}")
            
            if not domain_attached:
                print(f"[Pages] ⚠️ Could not attach domain automatically, but deployment succeeded")
                print(f"[Pages] ⚠️ The site is available at: {deployment_url}")
                print(f"[Pages] ⚠️ To attach the custom domain manually, run:")
                print(f"[Pages] ⚠️   npx wrangler pages domain add {custom_domain} --project-name {project_name}")
                print(f"[Pages] ⚠️ Or add manually in Cloudflare dashboard:")
                print(f"[Pages] ⚠️   https://dash.cloudflare.com -> Pages -> {project_name} -> Custom domains")
                
        except Exception as domain_err:
            print(f"[Pages] Warning: Could not add custom domain: {domain_err}")
            import traceback
            traceback.print_exc()
        
        # Return deployment information
        # For dev: returns preview.dev-vibe-*.pages.dev URL (stable preview URL)
        # For prod: returns vibe-*.pages.dev URL (stable production URL)
        # url: The stable URL (always points to latest for that branch)
        # deployment_url: The deployment-specific URL with hash (for this specific deployment)
        stable_pages_url = stable_url or deployment_url  # Use stable preview URL
        
        # CRITICAL: Ensure dev URLs ALWAYS use preview.* format (no DNS needed!)
        # This is the key to instant previews without waiting for DNS propagation
        if environment == "dev" and stable_pages_url:
            # Make sure we have the preview. prefix for dev deployments
            if '.pages.dev' in stable_pages_url and 'preview.' not in stable_pages_url:
                # Convert: https://dev-vibe-xyz.pages.dev → https://preview.dev-vibe-xyz.pages.dev
                # Convert: https://abc123.dev-vibe-xyz.pages.dev → https://preview.dev-vibe-xyz.pages.dev
                url_without_protocol = stable_pages_url.replace('https://', '')
                parts = url_without_protocol.split('.')
                
                # Find the project name (should be dev-vibe-* or first non-hash part)
                project_part = None
                for part in parts:
                    if 'dev-vibe-' in part or 'vibe-' in part:
                        project_part = part
                        break
                
                if project_part:
                    stable_pages_url = f"https://preview.{project_part}.pages.dev"
                    print(f"[Pages] 🔧 Corrected to preview URL: {stable_pages_url}")
        
        return jsonify({
            "success": True,
            "url": stable_pages_url,  # Stable URL (preview.{project}.pages.dev for dev, {project}.pages.dev for prod)
            "deployment_url": deployment_url,  # Deployment-specific URL with hash
            "stable_url": stable_url,  # Stable project URL (no hash, always latest)
            "project_name": project_name,
            "custom_domain": custom_domain,  # Custom domain (e.g., dev-vibe-*.quillworks.org or vibe-*.quillworks.org)
            "environment": environment,  # 'dev' or 'prod'
            "pages_dev_url": stable_pages_url if environment == "dev" else None,  # Stable dev preview URL (preview.{project}.pages.dev) - INSTANT, NO DNS
            "pages_prod_url": stable_pages_url if environment == "prod" else None,  # Stable prod URL ({project}.pages.dev)
            "custom_domain_url": f"https://{custom_domain}"  # Full custom domain URL
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Build/deploy timed out'}), 504
    except Exception as e:
        print(f"[Pages] Error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        # Cleanup temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


@app.route('/pages/attach-domain', methods=['POST'])
def attach_domain():
    """
    Manually attach a custom domain to a Cloudflare Pages project.
    Useful if automatic attachment failed during deployment.
    """
    try:
        data = request.json
        project_name = data.get('project_name')
        custom_domain = data.get('custom_domain')
        cf_account_id = data.get('cf_account_id') or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        cf_api_token = data.get('cf_api_token') or os.environ.get("CLOUDFLARE_API_TOKEN")
        cf_zone_id = data.get('cf_zone_id') or os.environ.get("CLOUDFLARE_ZONE_ID")
        
        if not project_name or not custom_domain:
            return jsonify({'error': 'Missing required fields: project_name, custom_domain'}), 400
        
        if not cf_account_id or not cf_api_token:
            return jsonify({'error': 'Missing Cloudflare credentials'}), 400
        
        import requests as req
        
        # Use Wrangler CLI (most reliable method)
        import tempfile
        temp_dir = tempfile.mkdtemp()
        env = os.environ.copy()
        env["CLOUDFLARE_API_TOKEN"] = cf_api_token
        env["CLOUDFLARE_ACCOUNT_ID"] = cf_account_id
        env["CLOUDFLARE_ZONE_ID"] = cf_zone_id
        
        # Use home directory or temp for Wrangler (doesn't need project files)
        wrangler_cwd = os.path.expanduser("~") if os.path.exists(os.path.expanduser("~")) else temp_dir
        
        # NOTE: wrangler pages domain add doesn't support --account-id
        # Authentication is handled via CLOUDFLARE_ACCOUNT_ID env var
        result = subprocess.run(
            [
                "npx", "--yes", "wrangler@latest", "pages", "domain", "add", custom_domain,
                "--project-name", project_name
            ],
            cwd=wrangler_cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=90
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': f'Custom domain {custom_domain} attached successfully',
                'method': 'wrangler',
                'command': f'npx wrangler pages domain add {custom_domain} --project-name {project_name}'
            })
        else:
            error_output = (result.stderr or result.stdout or "").lower()
            if any(phrase in error_output for phrase in ["already", "already exists", "already configured", "is already"]):
                return jsonify({
                    'success': True,
                    'message': f'Custom domain {custom_domain} already attached',
                    'method': 'wrangler'
                })
            else:
                # Return detailed error with command to run manually
                full_error = (result.stderr or result.stdout or "")[:1000]
                return jsonify({
                    'success': False,
                    'error': f'Wrangler failed to attach domain',
                    'wrangler_error': full_error,
                    'manual_command': f'npx wrangler pages domain add {custom_domain} --project-name {project_name}',
                    'dashboard_url': f'https://dash.cloudflare.com -> Pages -> {project_name} -> Custom domains'
                }), 500
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# PYTHON PROJECT DEPLOYMENT (Flask/Django/FastAPI)
# =============================================================================

# Track running Python projects: {project_id: {process, port, type, created_at}}
RUNNING_PYTHON_PROJECTS = {}
PYTHON_PORT_START = 9000  # Start assigning ports from 9000

def get_next_available_port():
    """Get the next available port for a Python project."""
    used_ports = {p['port'] for p in RUNNING_PYTHON_PROJECTS.values()}
    port = PYTHON_PORT_START
    while port in used_ports:
        port += 1
    return port

def cleanup_stopped_projects():
    """Clean up projects whose processes have stopped."""
    to_remove = []
    for project_id, info in RUNNING_PYTHON_PROJECTS.items():
        if info['process'].poll() is not None:  # Process has terminated
            to_remove.append(project_id)
            # Clean up temp directory
            if os.path.exists(info.get('temp_dir', '')):
                try:
                    shutil.rmtree(info['temp_dir'])
                except:
                    pass
    for project_id in to_remove:
        del RUNNING_PYTHON_PROJECTS[project_id]

@app.route('/deploy-python', methods=['POST'])
def deploy_python_project():
    """
    Deploy a Python project (Flask/Django/FastAPI).
    
    Expects JSON with:
    - project_id: Unique project identifier
    - framework: "flask" | "django" | "fastapi"
    - files: Array of {path, content} objects
    """
    cleanup_stopped_projects()
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400
    
    project_id = data.get('project_id')
    framework = data.get('framework', 'flask').lower()
    files = data.get('files', [])
    
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400
    
    if not files:
        return jsonify({'error': 'No files provided'}), 400
    
    if framework not in ['flask', 'django', 'fastapi']:
        return jsonify({'error': f'Unsupported framework: {framework}. Use flask, django, or fastapi'}), 400
    
    print(f"[Python Deploy] Starting deployment for project {project_id} ({framework})")
    print(f"[Python Deploy] Received {len(files)} files")
    
    # Stop existing project if running
    if project_id in RUNNING_PYTHON_PROJECTS:
        old_info = RUNNING_PYTHON_PROJECTS[project_id]
        try:
            old_info['process'].terminate()
            old_info['process'].wait(timeout=5)
        except:
            old_info['process'].kill()
        if os.path.exists(old_info.get('temp_dir', '')):
            try:
                shutil.rmtree(old_info['temp_dir'])
            except:
                pass
        del RUNNING_PYTHON_PROJECTS[project_id]
        print(f"[Python Deploy] Stopped existing project {project_id}")
    
    # Create temp directory for project
    temp_dir = tempfile.mkdtemp(prefix=f'python-{project_id}-')
    print(f"[Python Deploy] Created temp dir: {temp_dir}")
    
    try:
        # Write all files
        for file_info in files:
            file_path = file_info.get('path', '')
            content = file_info.get('content', '')
            
            if not file_path:
                continue
            
            # Normalize path and create directories
            file_path = file_path.lstrip('/')
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        print(f"[Python Deploy] Wrote {len(files)} files")
        
        # Create virtual environment
        print(f"[Python Deploy] Creating virtual environment...")
        venv_path = os.path.join(temp_dir, 'venv')
        venv_result = subprocess.run(
            ['python3', '-m', 'venv', venv_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if venv_result.returncode != 0:
            print(f"[Python Deploy] venv creation failed: {venv_result.stderr}")
            return jsonify({'error': f'Failed to create virtual environment: {venv_result.stderr}'}), 500
        
        # Determine pip and python paths
        if os.name == 'nt':  # Windows
            pip_path = os.path.join(venv_path, 'Scripts', 'pip')
            python_path = os.path.join(venv_path, 'Scripts', 'python')
        else:  # Unix
            pip_path = os.path.join(venv_path, 'bin', 'pip')
            python_path = os.path.join(venv_path, 'bin', 'python')
        
        # Install requirements if exists
        requirements_path = os.path.join(temp_dir, 'requirements.txt')
        if os.path.exists(requirements_path):
            print(f"[Python Deploy] Installing requirements...")
            install_result = subprocess.run(
                [pip_path, 'install', '-r', 'requirements.txt', '--quiet'],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes for installation
            )
            
            if install_result.returncode != 0:
                print(f"[Python Deploy] pip install failed: {install_result.stderr}")
                return jsonify({'error': f'Failed to install requirements: {install_result.stderr[:500]}'}), 500
            
            print(f"[Python Deploy] Requirements installed successfully")
        else:
            # Install framework if no requirements.txt
            framework_packages = {
                'flask': 'flask',
                'django': 'django',
                'fastapi': 'fastapi uvicorn'
            }
            print(f"[Python Deploy] No requirements.txt, installing {framework}...")
            subprocess.run(
                [pip_path, 'install'] + framework_packages[framework].split(),
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
        
        # Get port for this project
        port = get_next_available_port()
        print(f"[Python Deploy] Assigned port {port}")
        
        # Determine start command based on framework
        if framework == 'flask':
            # Look for app.py or main.py
            entry_file = 'app.py' if os.path.exists(os.path.join(temp_dir, 'app.py')) else 'main.py'
            cmd = [python_path, '-m', 'flask', 'run', '--host=0.0.0.0', f'--port={port}']
            env = {**os.environ, 'FLASK_APP': entry_file, 'FLASK_ENV': 'development'}
        elif framework == 'django':
            cmd = [python_path, 'manage.py', 'runserver', f'0.0.0.0:{port}']
            env = {**os.environ}
        elif framework == 'fastapi':
            # Look for main.py or app.py
            entry_file = 'main' if os.path.exists(os.path.join(temp_dir, 'main.py')) else 'app'
            cmd = [python_path, '-m', 'uvicorn', f'{entry_file}:app', '--host', '0.0.0.0', '--port', str(port)]
            env = {**os.environ}
        
        print(f"[Python Deploy] Starting with command: {' '.join(cmd)}")
        
        # Start the process
        process = subprocess.Popen(
            cmd,
            cwd=temp_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Give it a moment to start
        import time
        time.sleep(2)
        
        # Check if process is still running
        if process.poll() is not None:
            # Process died, get error
            stdout, stderr = process.communicate()
            error_msg = stderr.decode() if stderr else stdout.decode() if stdout else "Unknown error"
            print(f"[Python Deploy] Process failed to start: {error_msg}")
            shutil.rmtree(temp_dir)
            return jsonify({'error': f'Failed to start {framework} app: {error_msg[:500]}'}), 500
        
        # Store project info
        RUNNING_PYTHON_PROJECTS[project_id] = {
            'process': process,
            'port': port,
            'framework': framework,
            'temp_dir': temp_dir,
            'created_at': time.time()
        }
        
        # Build the URL
        # On Railway, we need to use the internal URL or expose via main app
        railway_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
        if railway_url:
            project_url = f"https://{railway_url}/python-app/{project_id}"
        else:
            project_url = f"http://localhost:{port}"
        
        print(f"[Python Deploy] ✅ Project {project_id} started on port {port}")
        print(f"[Python Deploy] URL: {project_url}")
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'framework': framework,
            'port': port,
            'url': project_url,
            'internal_url': f'http://localhost:{port}',
            'message': f'{framework.title()} app started successfully'
        })
        
    except Exception as e:
        print(f"[Python Deploy] Error: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({'error': str(e)}), 500


@app.route('/python-app/<project_id>', defaults={'path': ''})
@app.route('/python-app/<project_id>/<path:path>')
def proxy_python_app(project_id, path):
    """Proxy requests to running Python projects."""
    cleanup_stopped_projects()
    
    if project_id not in RUNNING_PYTHON_PROJECTS:
        return jsonify({'error': f'Project {project_id} not found or not running'}), 404
    
    project_info = RUNNING_PYTHON_PROJECTS[project_id]
    port = project_info['port']
    
    # Build target URL
    target_url = f'http://localhost:{port}/{path}'
    if request.query_string:
        target_url += f'?{request.query_string.decode()}'
    
    try:
        # Forward the request
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers={k: v for k, v in request.headers if k.lower() != 'host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )
        
        # Build response
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded_headers]
        
        return Response(resp.content, resp.status_code, headers)
        
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Failed to connect to Python app. It may still be starting.'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/stop-python/<project_id>', methods=['POST', 'DELETE'])
def stop_python_project(project_id):
    """Stop a running Python project."""
    if project_id not in RUNNING_PYTHON_PROJECTS:
        return jsonify({'error': f'Project {project_id} not found'}), 404
    
    project_info = RUNNING_PYTHON_PROJECTS[project_id]
    
    try:
        project_info['process'].terminate()
        project_info['process'].wait(timeout=5)
    except:
        project_info['process'].kill()
    
    # Clean up temp directory
    if os.path.exists(project_info.get('temp_dir', '')):
        try:
            shutil.rmtree(project_info['temp_dir'])
        except:
            pass
    
    del RUNNING_PYTHON_PROJECTS[project_id]
    
    print(f"[Python Deploy] Stopped project {project_id}")
    
    return jsonify({
        'success': True,
        'message': f'Project {project_id} stopped'
    })


@app.route('/python-projects', methods=['GET'])
def list_python_projects():
    """List all running Python projects."""
    cleanup_stopped_projects()
    
    import time
    projects = []
    for project_id, info in RUNNING_PYTHON_PROJECTS.items():
        projects.append({
            'project_id': project_id,
            'framework': info['framework'],
            'port': info['port'],
            'uptime_seconds': int(time.time() - info['created_at']),
            'status': 'running' if info['process'].poll() is None else 'stopped'
        })
    
    return jsonify({
        'projects': projects,
        'count': len(projects)
    })


# =============================================================================
# PHP/LARAVEL PROJECT DEPLOYMENT
# =============================================================================

# Track running PHP projects: {project_id: {process, port, type, created_at}}
RUNNING_PHP_PROJECTS = {}
PHP_PORT_START = 9500  # PHP projects start from port 9500

def check_php_available():
    """Check if PHP is installed and available."""
    try:
        result = subprocess.run(['php', '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def check_composer_available():
    """Check if Composer is installed and available."""
    try:
        result = subprocess.run(['composer', '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def get_next_php_port():
    """Get the next available port for a PHP project."""
    used_ports = {p['port'] for p in RUNNING_PHP_PROJECTS.values()}
    port = PHP_PORT_START
    while port in used_ports:
        port += 1
    return port

def cleanup_stopped_php_projects():
    """Clean up PHP projects whose processes have stopped."""
    to_remove = []
    for project_id, info in RUNNING_PHP_PROJECTS.items():
        if info['process'].poll() is not None:
            to_remove.append(project_id)
            if os.path.exists(info.get('temp_dir', '')):
                try:
                    shutil.rmtree(info['temp_dir'])
                except:
                    pass
    for project_id in to_remove:
        del RUNNING_PHP_PROJECTS[project_id]

@app.route('/deploy-php', methods=['POST'])
def deploy_php_project():
    """
    Deploy a PHP project (Laravel/vanilla PHP).
    
    Expects JSON with:
    - project_id: Unique project identifier
    - framework: "laravel" | "php"
    - files: Array of {path, content} objects
    """
    cleanup_stopped_php_projects()
    
    # Check PHP availability
    if not check_php_available():
        return jsonify({
            'error': 'PHP is not installed on this server',
            'setup_instructions': '''
To enable PHP support, add to your Railway service:
1. Create a Dockerfile with PHP installed
2. Or use Railway's PHP template
3. Or install PHP via nixpacks.toml:
   [phases.setup]
   nixPkgs = ["php82", "php82Packages.composer"]
'''
        }), 503
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400
    
    project_id = data.get('project_id')
    framework = data.get('framework', 'php').lower()
    files = data.get('files', [])
    
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400
    
    if not files:
        return jsonify({'error': 'No files provided'}), 400
    
    if framework not in ['laravel', 'php']:
        return jsonify({'error': f'Unsupported framework: {framework}. Use laravel or php'}), 400
    
    print(f"[PHP Deploy] Starting deployment for project {project_id} ({framework})")
    print(f"[PHP Deploy] Received {len(files)} files")
    
    # Stop existing project if running
    if project_id in RUNNING_PHP_PROJECTS:
        old_info = RUNNING_PHP_PROJECTS[project_id]
        try:
            old_info['process'].terminate()
            old_info['process'].wait(timeout=5)
        except:
            old_info['process'].kill()
        if os.path.exists(old_info.get('temp_dir', '')):
            try:
                shutil.rmtree(old_info['temp_dir'])
            except:
                pass
        del RUNNING_PHP_PROJECTS[project_id]
        print(f"[PHP Deploy] Stopped existing project {project_id}")
    
    # Create temp directory for project
    temp_dir = tempfile.mkdtemp(prefix=f'php-{project_id}-')
    print(f"[PHP Deploy] Created temp dir: {temp_dir}")
    
    try:
        # Write all files
        for file_info in files:
            file_path = file_info.get('path', '')
            content = file_info.get('content', '')
            
            if not file_path:
                continue
            
            file_path = file_path.lstrip('/')
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        print(f"[PHP Deploy] Wrote {len(files)} files")
        
        # Install Composer dependencies if composer.json exists
        composer_json = os.path.join(temp_dir, 'composer.json')
        if os.path.exists(composer_json) and check_composer_available():
            print(f"[PHP Deploy] Installing Composer dependencies...")
            install_result = subprocess.run(
                ['composer', 'install', '--no-interaction', '--prefer-dist'],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if install_result.returncode != 0:
                print(f"[PHP Deploy] Composer install failed: {install_result.stderr}")
                # Continue anyway - some projects might not need all dependencies
        
        # Get port for this project
        port = get_next_php_port()
        print(f"[PHP Deploy] Assigned port {port}")
        
        # Determine document root and start command
        if framework == 'laravel':
            # Laravel uses public/ as document root
            doc_root = os.path.join(temp_dir, 'public')
            if not os.path.exists(doc_root):
                doc_root = temp_dir
            
            # Run Laravel artisan serve if available
            artisan_path = os.path.join(temp_dir, 'artisan')
            if os.path.exists(artisan_path):
                cmd = ['php', 'artisan', 'serve', '--host=0.0.0.0', f'--port={port}']
                cwd = temp_dir
            else:
                cmd = ['php', '-S', f'0.0.0.0:{port}', '-t', 'public']
                cwd = temp_dir
        else:
            # Vanilla PHP - use built-in server
            cmd = ['php', '-S', f'0.0.0.0:{port}']
            cwd = temp_dir
        
        print(f"[PHP Deploy] Starting with command: {' '.join(cmd)}")
        
        # Start the process
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Give it a moment to start
        import time
        time.sleep(2)
        
        # Check if process is still running
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            error_msg = stderr.decode() if stderr else stdout.decode() if stdout else "Unknown error"
            print(f"[PHP Deploy] Process failed to start: {error_msg}")
            shutil.rmtree(temp_dir)
            return jsonify({'error': f'Failed to start {framework} app: {error_msg[:500]}'}), 500
        
        # Store project info
        RUNNING_PHP_PROJECTS[project_id] = {
            'process': process,
            'port': port,
            'framework': framework,
            'temp_dir': temp_dir,
            'created_at': time.time()
        }
        
        # Build the URL
        railway_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
        if railway_url:
            project_url = f"https://{railway_url}/php-app/{project_id}"
        else:
            project_url = f"http://localhost:{port}"
        
        print(f"[PHP Deploy] ✅ Project {project_id} started on port {port}")
        print(f"[PHP Deploy] URL: {project_url}")
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'framework': framework,
            'port': port,
            'url': project_url,
            'internal_url': f'http://localhost:{port}',
            'message': f'{framework.title()} app started successfully'
        })
        
    except Exception as e:
        print(f"[PHP Deploy] Error: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({'error': str(e)}), 500


@app.route('/php-app/<project_id>', defaults={'path': ''})
@app.route('/php-app/<project_id>/<path:path>')
def proxy_php_app(project_id, path):
    """Proxy requests to running PHP projects."""
    cleanup_stopped_php_projects()
    
    if project_id not in RUNNING_PHP_PROJECTS:
        return jsonify({'error': f'PHP project {project_id} not found or not running'}), 404
    
    project_info = RUNNING_PHP_PROJECTS[project_id]
    port = project_info['port']
    
    target_url = f'http://localhost:{port}/{path}'
    if request.query_string:
        target_url += f'?{request.query_string.decode()}'
    
    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers={k: v for k, v in request.headers if k.lower() != 'host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )
        
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded_headers]
        
        return Response(resp.content, resp.status_code, headers)
        
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Failed to connect to PHP app. It may still be starting.'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/stop-php/<project_id>', methods=['POST', 'DELETE'])
def stop_php_project(project_id):
    """Stop a running PHP project."""
    if project_id not in RUNNING_PHP_PROJECTS:
        return jsonify({'error': f'PHP project {project_id} not found'}), 404
    
    project_info = RUNNING_PHP_PROJECTS[project_id]
    
    try:
        project_info['process'].terminate()
        project_info['process'].wait(timeout=5)
    except:
        project_info['process'].kill()
    
    if os.path.exists(project_info.get('temp_dir', '')):
        try:
            shutil.rmtree(project_info['temp_dir'])
        except:
            pass
    
    del RUNNING_PHP_PROJECTS[project_id]
    
    print(f"[PHP Deploy] Stopped project {project_id}")
    
    return jsonify({
        'success': True,
        'message': f'PHP project {project_id} stopped'
    })


@app.route('/php-projects', methods=['GET'])
def list_php_projects():
    """List all running PHP projects."""
    cleanup_stopped_php_projects()
    
    import time
    projects = []
    for project_id, info in RUNNING_PHP_PROJECTS.items():
        projects.append({
            'project_id': project_id,
            'framework': info['framework'],
            'port': info['port'],
            'uptime_seconds': int(time.time() - info['created_at']),
            'status': 'running' if info['process'].poll() is None else 'stopped'
        })
    
    return jsonify({
        'projects': projects,
        'count': len(projects)
    })


# =============================================================================
# RUST PROJECT DEPLOYMENT
# =============================================================================

# Track running Rust projects: {project_id: {process, port, type, created_at}}
RUNNING_RUST_PROJECTS = {}
RUST_PORT_START = 10000  # Rust projects start from port 10000

def check_rust_available():
    """Check if Rust is installed and available."""
    try:
        result = subprocess.run(['rustc', '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def check_cargo_available():
    """Check if Cargo is installed and available."""
    try:
        result = subprocess.run(['cargo', '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def check_node_available():
    """Check if Node.js is installed and available."""
    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def get_next_rust_port():
    """Get the next available port for a Rust project."""
    used_ports = {p['port'] for p in RUNNING_RUST_PROJECTS.values()}
    port = RUST_PORT_START
    while port in used_ports:
        port += 1
    return port

def cleanup_stopped_rust_projects():
    """Clean up Rust projects whose processes have stopped."""
    to_remove = []
    for project_id, info in RUNNING_RUST_PROJECTS.items():
        if info['process'].poll() is not None:
            to_remove.append(project_id)
            if os.path.exists(info.get('temp_dir', '')):
                try:
                    shutil.rmtree(info['temp_dir'])
                except:
                    pass
    for project_id in to_remove:
        del RUNNING_RUST_PROJECTS[project_id]

@app.route('/deploy-rust', methods=['POST'])
def deploy_rust_project():
    """
    Deploy a Rust project (Actix-web, Axum, Rocket, etc.).
    
    Expects JSON with:
    - project_id: Unique project identifier
    - framework: "actix" | "axum" | "rocket" | "rust"
    - files: Array of {path, content} objects
    """
    cleanup_stopped_rust_projects()
    
    # Check Rust availability
    if not check_rust_available() or not check_cargo_available():
        return jsonify({
            'error': 'Rust/Cargo is not installed on this server',
            'setup_instructions': 'Rust should be installed via the Dockerfile. Please rebuild the container.'
        }), 503
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400
    
    project_id = data.get('project_id')
    framework = data.get('framework', 'rust').lower()
    files = data.get('files', [])
    
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400
    
    if not files:
        return jsonify({'error': 'No files provided'}), 400
    
    print(f"[Rust Deploy] Starting deployment for project {project_id} ({framework})")
    print(f"[Rust Deploy] Received {len(files)} files")
    
    # Stop existing project if running
    if project_id in RUNNING_RUST_PROJECTS:
        old_info = RUNNING_RUST_PROJECTS[project_id]
        try:
            old_info['process'].terminate()
            old_info['process'].wait(timeout=5)
        except:
            old_info['process'].kill()
        if os.path.exists(old_info.get('temp_dir', '')):
            try:
                shutil.rmtree(old_info['temp_dir'])
            except:
                pass
        del RUNNING_RUST_PROJECTS[project_id]
        print(f"[Rust Deploy] Stopped existing project {project_id}")
    
    # Create temp directory for project
    temp_dir = tempfile.mkdtemp(prefix=f'rust-{project_id}-')
    print(f"[Rust Deploy] Created temp dir: {temp_dir}")
    
    try:
        # Write all files
        for file_info in files:
            file_path = file_info.get('path', '')
            content = file_info.get('content', '')
            
            if not file_path:
                continue
            
            file_path = file_path.lstrip('/')
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        print(f"[Rust Deploy] Wrote {len(files)} files")
        
        # Check if Cargo.toml exists
        cargo_toml = os.path.join(temp_dir, 'Cargo.toml')
        if not os.path.exists(cargo_toml):
            return jsonify({'error': 'No Cargo.toml found. This is required for Rust projects.'}), 400
        
        # Build the Rust project
        print(f"[Rust Deploy] Building Rust project with cargo build --release...")
        build_result = subprocess.run(
            ['cargo', 'build', '--release'],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes for Rust compilation
        )
        
        if build_result.returncode != 0:
            print(f"[Rust Deploy] Build failed: {build_result.stderr}")
            return jsonify({
                'error': f'Rust build failed',
                'stderr': build_result.stderr[:1000],
                'stdout': build_result.stdout[:1000]
            }), 500
        
        print(f"[Rust Deploy] Build completed successfully")
        
        # Find the built binary
        target_dir = os.path.join(temp_dir, 'target', 'release')
        binaries = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f)) and os.access(os.path.join(target_dir, f), os.X_OK)]
        
        # Filter out common non-executable files
        binaries = [b for b in binaries if not b.endswith('.d') and not b.endswith('.rlib') and not b.startswith('.')]
        
        if not binaries:
            return jsonify({'error': 'No executable binary found after build'}), 500
        
        # Use the first binary (usually there's only one)
        binary_name = binaries[0]
        binary_path = os.path.join(target_dir, binary_name)
        
        print(f"[Rust Deploy] Found binary: {binary_name}")
        
        # Get port for this project
        port = get_next_rust_port()
        print(f"[Rust Deploy] Assigned port {port}")
        
        # Run the binary with PORT environment variable
        env = {**os.environ, 'PORT': str(port), 'HOST': '0.0.0.0'}
        
        process = subprocess.Popen(
            [binary_path],
            cwd=temp_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Give it a moment to start
        import time
        time.sleep(3)
        
        # Check if process is still running
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            error_msg = stderr.decode() if stderr else stdout.decode() if stdout else "Unknown error"
            print(f"[Rust Deploy] Process failed to start: {error_msg}")
            shutil.rmtree(temp_dir)
            return jsonify({'error': f'Failed to start Rust app: {error_msg[:500]}'}), 500
        
        # Store project info
        RUNNING_RUST_PROJECTS[project_id] = {
            'process': process,
            'port': port,
            'framework': framework,
            'temp_dir': temp_dir,
            'binary': binary_name,
            'created_at': time.time()
        }
        
        # Build the URL
        railway_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
        if railway_url:
            project_url = f"https://{railway_url}/rust-app/{project_id}"
        else:
            project_url = f"http://localhost:{port}"
        
        print(f"[Rust Deploy] ✅ Project {project_id} started on port {port}")
        print(f"[Rust Deploy] URL: {project_url}")
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'framework': framework,
            'port': port,
            'url': project_url,
            'internal_url': f'http://localhost:{port}',
            'binary': binary_name,
            'message': f'Rust ({framework}) app started successfully'
        })
        
    except subprocess.TimeoutExpired:
        print(f"[Rust Deploy] Build timed out")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({'error': 'Rust build timed out (10 minute limit)'}), 500
    except Exception as e:
        print(f"[Rust Deploy] Error: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({'error': str(e)}), 500


@app.route('/rust-app/<project_id>', defaults={'path': ''})
@app.route('/rust-app/<project_id>/<path:path>')
def proxy_rust_app(project_id, path):
    """Proxy requests to running Rust projects."""
    cleanup_stopped_rust_projects()
    
    if project_id not in RUNNING_RUST_PROJECTS:
        return jsonify({'error': f'Rust project {project_id} not found or not running'}), 404
    
    project_info = RUNNING_RUST_PROJECTS[project_id]
    port = project_info['port']
    
    target_url = f'http://localhost:{port}/{path}'
    if request.query_string:
        target_url += f'?{request.query_string.decode()}'
    
    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers={k: v for k, v in request.headers if k.lower() != 'host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )
        
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded_headers]
        
        return Response(resp.content, resp.status_code, headers)
        
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Failed to connect to Rust app. It may still be starting.'}), 503
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/stop-rust/<project_id>', methods=['POST', 'DELETE'])
def stop_rust_project(project_id):
    """Stop a running Rust project."""
    if project_id not in RUNNING_RUST_PROJECTS:
        return jsonify({'error': f'Rust project {project_id} not found'}), 404
    
    project_info = RUNNING_RUST_PROJECTS[project_id]
    
    try:
        project_info['process'].terminate()
        project_info['process'].wait(timeout=5)
    except:
        project_info['process'].kill()
    
    if os.path.exists(project_info.get('temp_dir', '')):
        try:
            shutil.rmtree(project_info['temp_dir'])
        except:
            pass
    
    del RUNNING_RUST_PROJECTS[project_id]
    
    print(f"[Rust Deploy] Stopped project {project_id}")
    
    return jsonify({
        'success': True,
        'message': f'Rust project {project_id} stopped'
    })


@app.route('/rust-projects', methods=['GET'])
def list_rust_projects():
    """List all running Rust projects."""
    cleanup_stopped_rust_projects()
    
    import time
    projects = []
    for project_id, info in RUNNING_RUST_PROJECTS.items():
        projects.append({
            'project_id': project_id,
            'framework': info['framework'],
            'port': info['port'],
            'binary': info.get('binary', 'unknown'),
            'uptime_seconds': int(time.time() - info['created_at']),
            'status': 'running' if info['process'].poll() is None else 'stopped'
        })
    
    return jsonify({
        'projects': projects,
        'count': len(projects)
    })


# =============================================================================
# GO PROJECT DEPLOYMENT
# =============================================================================

RUNNING_GO_PROJECTS = {}  # project_id -> {process, port, framework, created_at, temp_dir}


def check_go_available():
    """Check if Go is available on the system."""
    try:
        result = subprocess.run(['go', 'version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def get_next_go_port():
    """Get the next available port for a Go project (starts at 10000)."""
    used_ports = {info['port'] for info in RUNNING_GO_PROJECTS.values()}
    port = 10000
    while port in used_ports:
        port += 1
    return port


def cleanup_stopped_go_projects():
    """Clean up any stopped Go projects."""
    stopped = []
    for project_id, info in RUNNING_GO_PROJECTS.items():
        if info['process'].poll() is not None:
            stopped.append(project_id)
            # Clean up temp directory
            if 'temp_dir' in info and os.path.exists(info['temp_dir']):
                import shutil
                shutil.rmtree(info['temp_dir'], ignore_errors=True)
    for project_id in stopped:
        del RUNNING_GO_PROJECTS[project_id]


@app.route('/deploy-go', methods=['POST'])
def deploy_go_project():
    """Deploy a Go project."""
    import shutil
    
    # Check if Go is available
    if not check_go_available():
        return jsonify({
            'success': False,
            'error': 'Go is not installed on this server',
            'setup_instructions': 'Install Go from https://go.dev/dl/'
        }), 500
    
    data = request.json
    project_id = data.get('project_id')
    files = data.get('files', {})
    framework = data.get('framework', 'go')  # go, gin, echo, fiber
    
    if not project_id:
        return jsonify({'success': False, 'error': 'project_id is required'}), 400
    
    if not files:
        return jsonify({'success': False, 'error': 'No files provided'}), 400
    
    print(f"[Go Deploy] Starting deployment for project {project_id}")
    print(f"[Go Deploy] Framework: {framework}")
    print(f"[Go Deploy] Files: {list(files.keys())}")
    
    # Stop existing project if running
    if project_id in RUNNING_GO_PROJECTS:
        old_info = RUNNING_GO_PROJECTS[project_id]
        try:
            old_info['process'].terminate()
            old_info['process'].wait(timeout=5)
        except:
            old_info['process'].kill()
        if 'temp_dir' in old_info and os.path.exists(old_info['temp_dir']):
            shutil.rmtree(old_info['temp_dir'], ignore_errors=True)
        del RUNNING_GO_PROJECTS[project_id]
    
    # Create temp directory for the project
    temp_dir = tempfile.mkdtemp(prefix=f'go_project_{project_id}_')
    print(f"[Go Deploy] Created temp directory: {temp_dir}")
    
    try:
        # Write all files
        for file_path, content in files.items():
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[Go Deploy] Created file: {file_path}")
        
        # Check for go.mod
        go_mod_path = os.path.join(temp_dir, 'go.mod')
        if not os.path.exists(go_mod_path):
            # Initialize go module
            print("[Go Deploy] Initializing go module...")
            result = subprocess.run(
                ['go', 'mod', 'init', f'project_{project_id}'],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                print(f"[Go Deploy] go mod init output: {result.stderr}")
        
        # Download dependencies
        print("[Go Deploy] Downloading dependencies...")
        result = subprocess.run(
            ['go', 'mod', 'tidy'],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, 'GOPATH': '/go', 'GOCACHE': '/tmp/go-cache'}
        )
        if result.returncode != 0:
            print(f"[Go Deploy] go mod tidy error: {result.stderr}")
        
        # Build the project
        print("[Go Deploy] Building project...")
        binary_name = f'app_{project_id}'
        binary_path = os.path.join(temp_dir, binary_name)
        
        result = subprocess.run(
            ['go', 'build', '-o', binary_name, '.'],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, 'GOPATH': '/go', 'GOCACHE': '/tmp/go-cache', 'CGO_ENABLED': '0'}
        )
        
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': 'Go build failed',
                'build_error': result.stderr,
                'build_output': result.stdout
            }), 400
        
        print(f"[Go Deploy] Build successful: {binary_path}")
        
        # Get port for this project
        port = get_next_go_port()
        
        # Start the Go application
        print(f"[Go Deploy] Starting Go app on port {port}...")
        
        env = os.environ.copy()
        env['PORT'] = str(port)
        env['GIN_MODE'] = 'release'  # For Gin framework
        
        process = subprocess.Popen(
            [binary_path],
            cwd=temp_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a moment for startup
        import time
        time.sleep(2)
        
        # Check if process started successfully
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            return jsonify({
                'success': False,
                'error': 'Go application failed to start',
                'stderr': stderr.decode('utf-8', errors='replace'),
                'stdout': stdout.decode('utf-8', errors='replace')
            }), 500
        
        # Store project info
        RUNNING_GO_PROJECTS[project_id] = {
            'process': process,
            'port': port,
            'framework': framework,
            'binary': binary_name,
            'temp_dir': temp_dir,
            'created_at': time.time()
        }
        
        base_url = request.host_url.rstrip('/')
        app_url = f"{base_url}/go-app/{project_id}"
        
        print(f"[Go Deploy] Project {project_id} deployed successfully at {app_url}")
        
        return jsonify({
            'success': True,
            'message': f'Go project deployed successfully',
            'project_id': project_id,
            'port': port,
            'app_url': app_url,
            'framework': framework,
            'binary': binary_name
        })
        
    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[Go Deploy] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/go-app/<project_id>', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
@app.route('/go-app/<project_id>/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def proxy_go_app(project_id, path):
    """Proxy requests to a running Go project."""
    if project_id not in RUNNING_GO_PROJECTS:
        return jsonify({'error': f'Go project {project_id} not found or not running'}), 404
    
    info = RUNNING_GO_PROJECTS[project_id]
    
    # Check if process is still running
    if info['process'].poll() is not None:
        del RUNNING_GO_PROJECTS[project_id]
        return jsonify({'error': f'Go project {project_id} has stopped'}), 500
    
    port = info['port']
    target_url = f"http://127.0.0.1:{port}/{path}"
    
    try:
        # Forward the request
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers={k: v for k, v in request.headers if k.lower() != 'host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )
        
        # Build response
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded_headers]
        
        return Response(resp.content, resp.status_code, headers)
        
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Could not connect to Go application'}), 502
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Go application timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/stop-go/<project_id>', methods=['POST'])
def stop_go_project(project_id):
    """Stop a running Go project."""
    import shutil
    
    if project_id not in RUNNING_GO_PROJECTS:
        return jsonify({'error': f'Go project {project_id} not found'}), 404
    
    info = RUNNING_GO_PROJECTS[project_id]
    
    # Terminate the process
    try:
        info['process'].terminate()
        info['process'].wait(timeout=5)
    except:
        info['process'].kill()
    
    # Clean up temp directory
    if 'temp_dir' in info and os.path.exists(info['temp_dir']):
        shutil.rmtree(info['temp_dir'], ignore_errors=True)
    
    del RUNNING_GO_PROJECTS[project_id]
    
    print(f"[Go Deploy] Stopped project {project_id}")
    
    return jsonify({
        'success': True,
        'message': f'Go project {project_id} stopped'
    })


@app.route('/go-projects', methods=['GET'])
def list_go_projects():
    """List all running Go projects."""
    cleanup_stopped_go_projects()
    
    import time
    projects = []
    for project_id, info in RUNNING_GO_PROJECTS.items():
        projects.append({
            'project_id': project_id,
            'framework': info['framework'],
            'port': info['port'],
            'binary': info.get('binary', 'unknown'),
            'uptime_seconds': int(time.time() - info['created_at']),
            'status': 'running' if info['process'].poll() is None else 'stopped'
        })
    
    return jsonify({
        'projects': projects,
        'count': len(projects)
    })


# =============================================================================
# ANDROID PROJECT BUILD
# =============================================================================

BUILT_ANDROID_APKS = {}  # project_id -> {apk_path, created_at, temp_dir}


def check_java_available():
    """Check if Java is available on the system."""
    try:
        result = subprocess.run(['java', '-version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def check_android_sdk_available():
    """Check if Android SDK is available on the system."""
    android_home = os.environ.get('ANDROID_HOME', '/opt/android-sdk')
    sdkmanager = os.path.join(android_home, 'cmdline-tools', 'latest', 'bin', 'sdkmanager')
    return os.path.exists(sdkmanager)


def cleanup_old_android_builds():
    """Clean up Android builds older than 1 hour."""
    import time
    import shutil
    
    expired = []
    for project_id, info in BUILT_ANDROID_APKS.items():
        if time.time() - info['created_at'] > 3600:  # 1 hour
            expired.append(project_id)
            if 'temp_dir' in info and os.path.exists(info['temp_dir']):
                shutil.rmtree(info['temp_dir'], ignore_errors=True)
    for project_id in expired:
        del BUILT_ANDROID_APKS[project_id]


@app.route('/build-android', methods=['POST'])
def build_android_project():
    """Build an Android APK from project files."""
    import shutil
    
    # Check prerequisites
    if not check_java_available():
        return jsonify({
            'success': False,
            'error': 'Java is not installed on this server',
            'setup_instructions': 'Install OpenJDK 17: apt-get install openjdk-17-jdk-headless'
        }), 500
    
    if not check_android_sdk_available():
        return jsonify({
            'success': False,
            'error': 'Android SDK is not installed on this server',
            'setup_instructions': 'Install Android SDK command-line tools'
        }), 500
    
    data = request.json
    project_id = data.get('project_id')
    files = data.get('files', {})
    app_name = data.get('app_name', 'MyApp')
    package_name = data.get('package_name', 'com.example.myapp')
    
    if not project_id:
        return jsonify({'success': False, 'error': 'project_id is required'}), 400
    
    if not files:
        return jsonify({'success': False, 'error': 'No files provided'}), 400
    
    print(f"[Android Build] Starting build for project {project_id}")
    print(f"[Android Build] App name: {app_name}")
    print(f"[Android Build] Package: {package_name}")
    print(f"[Android Build] Files: {list(files.keys())}")
    
    # Clean up old build if exists
    if project_id in BUILT_ANDROID_APKS:
        old_info = BUILT_ANDROID_APKS[project_id]
        if 'temp_dir' in old_info and os.path.exists(old_info['temp_dir']):
            shutil.rmtree(old_info['temp_dir'], ignore_errors=True)
        del BUILT_ANDROID_APKS[project_id]
    
    # Create temp directory for the project
    temp_dir = tempfile.mkdtemp(prefix=f'android_project_{project_id}_')
    print(f"[Android Build] Created temp directory: {temp_dir}")
    
    try:
        # Write all files
        for file_path, content in files.items():
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[Android Build] Created file: {file_path}")
        
        # Check if this is a Gradle project
        has_gradle = os.path.exists(os.path.join(temp_dir, 'build.gradle')) or \
                     os.path.exists(os.path.join(temp_dir, 'build.gradle.kts'))
        has_gradlew = os.path.exists(os.path.join(temp_dir, 'gradlew'))
        
        if not has_gradle:
            # Create a basic Android project structure if not provided
            print("[Android Build] No build.gradle found, creating basic project structure...")
            create_basic_android_project(temp_dir, app_name, package_name, files)
            has_gradlew = True  # We create gradlew
        
        # Make gradlew executable
        gradlew_path = os.path.join(temp_dir, 'gradlew')
        if os.path.exists(gradlew_path):
            os.chmod(gradlew_path, 0o755)
        
        # Set up environment
        android_home = os.environ.get('ANDROID_HOME', '/opt/android-sdk')
        build_env = os.environ.copy()
        build_env['ANDROID_HOME'] = android_home
        build_env['ANDROID_SDK_ROOT'] = android_home
        
        # Build the APK
        print("[Android Build] Running Gradle build...")
        
        if has_gradlew:
            build_cmd = ['./gradlew', 'assembleDebug', '--no-daemon', '-q']
        else:
            build_cmd = ['gradle', 'assembleDebug', '--no-daemon', '-q']
        
        result = subprocess.run(
            build_cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout for builds
            env=build_env
        )
        
        if result.returncode != 0:
            print(f"[Android Build] Build failed: {result.stderr}")
            return jsonify({
                'success': False,
                'error': 'Android build failed',
                'build_error': result.stderr,
                'build_output': result.stdout
            }), 400
        
        # Find the APK
        apk_path = None
        for root, dirs, apk_files in os.walk(os.path.join(temp_dir, 'app', 'build', 'outputs', 'apk')):
            for apk_file in apk_files:
                if apk_file.endswith('.apk'):
                    apk_path = os.path.join(root, apk_file)
                    break
            if apk_path:
                break
        
        if not apk_path or not os.path.exists(apk_path):
            return jsonify({
                'success': False,
                'error': 'APK file not found after build',
                'build_output': result.stdout
            }), 500
        
        # Get APK size
        apk_size = os.path.getsize(apk_path)
        
        # Store build info
        import time
        BUILT_ANDROID_APKS[project_id] = {
            'apk_path': apk_path,
            'temp_dir': temp_dir,
            'app_name': app_name,
            'package_name': package_name,
            'created_at': time.time(),
            'apk_size': apk_size
        }
        
        base_url = request.host_url.rstrip('/')
        download_url = f"{base_url}/download-apk/{project_id}"
        
        print(f"[Android Build] Build successful!")
        print(f"[Android Build] APK path: {apk_path}")
        print(f"[Android Build] APK size: {apk_size} bytes")
        print(f"[Android Build] Download URL: {download_url}")
        
        return jsonify({
            'success': True,
            'message': 'Android APK built successfully',
            'project_id': project_id,
            'download_url': download_url,
            'apk_size': apk_size,
            'app_name': app_name,
            'package_name': package_name
        })
        
    except subprocess.TimeoutExpired:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({
            'success': False,
            'error': 'Build timed out (10 minute limit exceeded)'
        }), 500
    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[Android Build] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def create_basic_android_project(temp_dir, app_name, package_name, user_files):
    """Create a basic Android project structure for simple apps."""
    import shutil
    
    package_path = package_name.replace('.', '/')
    
    # Create directory structure
    os.makedirs(os.path.join(temp_dir, 'app', 'src', 'main', 'java', package_path), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'app', 'src', 'main', 'res', 'layout'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'app', 'src', 'main', 'res', 'values'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'gradle', 'wrapper'), exist_ok=True)
    
    # settings.gradle
    settings_gradle = f'''pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}
dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        google()
        mavenCentral()
    }}
}}
rootProject.name = "{app_name}"
include ':app'
'''
    with open(os.path.join(temp_dir, 'settings.gradle'), 'w') as f:
        f.write(settings_gradle)
    
    # Root build.gradle
    root_build_gradle = '''plugins {
    id 'com.android.application' version '8.2.0' apply false
    id 'org.jetbrains.kotlin.android' version '1.9.0' apply false
}
'''
    with open(os.path.join(temp_dir, 'build.gradle'), 'w') as f:
        f.write(root_build_gradle)
    
    # App build.gradle
    app_build_gradle = f'''plugins {{
    id 'com.android.application'
}}

android {{
    namespace '{package_name}'
    compileSdk 34

    defaultConfig {{
        applicationId "{package_name}"
        minSdk 24
        targetSdk 34
        versionCode 1
        versionName "1.0"
    }}

    buildTypes {{
        release {{
            minifyEnabled false
        }}
        debug {{
            minifyEnabled false
        }}
    }}
    compileOptions {{
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }}
}}

dependencies {{
    implementation 'androidx.appcompat:appcompat:1.6.1'
    implementation 'com.google.android.material:material:1.11.0'
    implementation 'androidx.constraintlayout:constraintlayout:2.1.4'
}}
'''
    with open(os.path.join(temp_dir, 'app', 'build.gradle'), 'w') as f:
        f.write(app_build_gradle)
    
    # AndroidManifest.xml
    manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application
        android:allowBackup="true"
        android:label="{app_name}"
        android:supportsRtl="true"
        android:theme="@style/Theme.Material3.DayNight">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
'''
    with open(os.path.join(temp_dir, 'app', 'src', 'main', 'AndroidManifest.xml'), 'w') as f:
        f.write(manifest)
    
    # Check if user provided MainActivity, otherwise create default
    has_main_activity = any('MainActivity' in f for f in user_files.keys())
    
    if not has_main_activity:
        # Default MainActivity.java
        main_activity = f'''package {package_name};

import android.os.Bundle;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
    }}
}}
'''
        with open(os.path.join(temp_dir, 'app', 'src', 'main', 'java', package_path, 'MainActivity.java'), 'w') as f:
            f.write(main_activity)
    
    # Default layout
    has_layout = any('activity_main.xml' in f for f in user_files.keys())
    
    if not has_layout:
        layout = f'''<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout 
    xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="match_parent">

    <TextView
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="Hello, {app_name}!"
        android:textSize="24sp"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintTop_toTopOf="parent" />

</androidx.constraintlayout.widget.ConstraintLayout>
'''
        with open(os.path.join(temp_dir, 'app', 'src', 'main', 'res', 'layout', 'activity_main.xml'), 'w') as f:
            f.write(layout)
    
    # strings.xml
    strings = f'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
</resources>
'''
    with open(os.path.join(temp_dir, 'app', 'src', 'main', 'res', 'values', 'strings.xml'), 'w') as f:
        f.write(strings)
    
    # gradle-wrapper.properties
    wrapper_props = '''distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\\://services.gradle.org/distributions/gradle-8.2-bin.zip
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
'''
    with open(os.path.join(temp_dir, 'gradle', 'wrapper', 'gradle-wrapper.properties'), 'w') as f:
        f.write(wrapper_props)
    
    # gradlew script
    gradlew = '''#!/bin/sh
exec gradle "$@"
'''
    with open(os.path.join(temp_dir, 'gradlew'), 'w') as f:
        f.write(gradlew)
    os.chmod(os.path.join(temp_dir, 'gradlew'), 0o755)
    
    print(f"[Android Build] Created basic Android project structure for {app_name}")


@app.route('/download-apk/<project_id>', methods=['GET'])
def download_apk(project_id):
    """Download a built APK file."""
    cleanup_old_android_builds()
    
    if project_id not in BUILT_ANDROID_APKS:
        return jsonify({'error': f'APK for project {project_id} not found or expired'}), 404
    
    info = BUILT_ANDROID_APKS[project_id]
    apk_path = info['apk_path']
    
    if not os.path.exists(apk_path):
        del BUILT_ANDROID_APKS[project_id]
        return jsonify({'error': 'APK file no longer exists'}), 404
    
    app_name = info.get('app_name', 'app')
    filename = f"{app_name.replace(' ', '_')}-debug.apk"
    
    return send_file(
        apk_path,
        mimetype='application/vnd.android.package-archive',
        as_attachment=True,
        download_name=filename
    )


@app.route('/android-builds', methods=['GET'])
def list_android_builds():
    """List all available Android builds."""
    cleanup_old_android_builds()
    
    import time
    builds = []
    base_url = request.host_url.rstrip('/')
    
    for project_id, info in BUILT_ANDROID_APKS.items():
        builds.append({
            'project_id': project_id,
            'app_name': info.get('app_name', 'Unknown'),
            'package_name': info.get('package_name', 'Unknown'),
            'apk_size': info.get('apk_size', 0),
            'download_url': f"{base_url}/download-apk/{project_id}",
            'age_seconds': int(time.time() - info['created_at']),
            'expires_in_seconds': max(0, 3600 - int(time.time() - info['created_at']))
        })
    
    return jsonify({
        'builds': builds,
        'count': len(builds)
    })


# Update runtime-status to include Go and Android
@app.route('/runtime-status', methods=['GET'])
def runtime_status():
    """Check the status of all available runtimes."""
    cleanup_stopped_projects()
    cleanup_stopped_php_projects()
    cleanup_stopped_rust_projects()
    cleanup_stopped_go_projects()
    cleanup_old_android_builds()
    
    return jsonify({
        'runtimes': {
            'python': True,  # Always available (this is a Python app)
            'php': check_php_available(),
            'composer': check_composer_available(),
            'rust': check_rust_available(),
            'cargo': check_cargo_available(),
            'node': check_node_available(),
            'go': check_go_available(),
            'java': check_java_available(),
            'android_sdk': check_android_sdk_available()
        },
        'running_projects': {
            'python': len(RUNNING_PYTHON_PROJECTS),
            'php': len(RUNNING_PHP_PROJECTS),
            'rust': len(RUNNING_RUST_PROJECTS),
            'go': len(RUNNING_GO_PROJECTS)
        },
        'android_builds': len(BUILT_ANDROID_APKS)
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
