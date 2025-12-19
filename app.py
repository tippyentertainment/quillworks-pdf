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

from flask import Flask, request, jsonify, send_file
from io import BytesIO
import os

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

try:
    from rembg import remove
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False
    print("WARNING: rembg not available")

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
    )
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
            'design_service': DESIGN_SERVICE_AVAILABLE
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
        print(f"Error generating design: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


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
    if not REMBG_AVAILABLE:
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
        
        output_buffer.write(remove(input_buffer.read()))
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

@app.route('/generate-recipe-book-pdf', methods=['POST'])
def generate_recipe_book_pdf():
    """Generate PDF for recipe books with two-page spreads matching the preview"""
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
from PIL import Image as PILImage
import base64
import io

@app.route('/remove-background', methods=['POST'])
def remove_background():
    """Remove background from an image given by URL or data URL (base64). Returns PNG with transparent background."""
    try:
        data = request.get_json(force=True)
        image_url = data.get('image_url')
        if not image_url:
            return jsonify({'error': 'Missing image_url'}), 400

        # Handle data URL (base64)
        if image_url.startswith('data:image'):
            header, encoded = image_url.split(',', 1)
            image_bytes = base64.b64decode(encoded)
            image = PILImage.open(io.BytesIO(image_bytes)).convert('RGBA')
        else:
            # Assume direct URL
            resp = requests.get(image_url)
            if resp.status_code != 200:
                return jsonify({'error': 'Failed to fetch image from URL'}), 400
            image = PILImage.open(io.BytesIO(resp.content)).convert('RGBA')

        # Simple background removal: make all white pixels transparent
        datas = image.getdata()
        newData = []
        for item in datas:
            # Detect white-ish pixels
            if item[0] > 240 and item[1] > 240 and item[2] > 240:
                newData.append((255, 255, 255, 0))
            else:
                newData.append(item)
        image.putdata(newData)

        output = io.BytesIO()
        image.save(output, format='PNG')
        output.seek(0)
        return send_file(output, mimetype='image/png', as_attachment=True, download_name='result.png')
    except Exception as e:
        return jsonify({'error': f'Background removal failed: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
