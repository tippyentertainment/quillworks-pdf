"""
Simple PDF Generation Service for QuillWorks.AI
Deploy this on Railway, Render, Fly.io, or any Python hosting platform.

Install dependencies:
pip install flask reportlab pillow requests python-dotenv

Run locally:
python app.py

Deploy to Railway/Render with Procfile:
web: gunicorn app:app
"""

from flask import Flask, request, jsonify, send_file
from reportlab.lib.pagesizes import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import inch
from io import BytesIO
import requests
import os
from datetime import datetime

app = Flask(__name__)

# Register fonts
try:
    pdfmetrics.registerFont(TTFont('Bembo', 'fonts/Bembo.ttf'))
    pdfmetrics.registerFont(TTFont('Bembo-Italic', 'fonts/Bembo-Italic.ttf'))
    pdfmetrics.registerFont(TTFont('Bembo-Bold', 'fonts/Bembo-Bold.ttf'))
    FONT_FAMILY = 'Bembo'
except:
    # Fallback to built-in fonts
    FONT_FAMILY = 'Times-Roman'

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'pdf-generator'})

@app.route('/generate-book-pdf', methods=['POST'])
def generate_book_pdf():
    """Generate PDF for regular books"""
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
            rightMargin=0.5*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        
        # Build PDF content
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
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
            spaceAfter=12
        )
        
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontName=FONT_FAMILY,
            fontSize=book_data.get('font_size', 11),
            leading=book_data.get('font_size', 11) * 1.5,
            textColor=colors.black,
            alignment=TA_JUSTIFY,
            firstLineIndent=0.3*inch
        )
        
        # Title page
        story.append(Spacer(1, 2*inch))
        story.append(Paragraph(book_data.get('book_title', 'Untitled'), title_style))
        story.append(Paragraph(f"by {book_data.get('author_name', 'Author')}", author_style))
        if book_data.get('genre'):
            story.append(Paragraph(book_data['genre'], author_style))
        story.append(PageBreak())
        
        # Dedication
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
        
        # About the Author
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
        
        # Table of Contents
        story.append(Paragraph("Table of Contents", chapter_title_style))
        story.append(Spacer(1, 12))
        
        for i, chapter in enumerate(book_data.get('chapters', [])):
            toc_entry = f"{chapter.get('title', f'Chapter {chapter.get('number', i+1)')}"
            story.append(Paragraph(toc_entry, body_style))
            story.append(Spacer(1, 6))
        
        story.append(PageBreak())
        
        # Chapters
        for chapter in book_data.get('chapters', []):
            # Chapter title
            story.append(Paragraph(str(chapter.get('number', '')), chapter_title_style))
            story.append(Paragraph(chapter.get('title', ''), chapter_title_style))
            story.append(Spacer(1, 24))
            
            # Chapter content
            content = chapter.get('content', '')
            # Split into paragraphs
            paragraphs = content.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    story.append(Paragraph(para.strip(), body_style))
                    story.append(Spacer(1, 12))
            
            story.append(PageBreak())
        
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
