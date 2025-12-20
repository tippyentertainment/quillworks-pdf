"""
Flyer PDF generation module.
"""

from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import requests


def generate_flyer_pdf(flyer_data: dict) -> BytesIO:
    """
    Generate a PDF flyer from the provided data.
    
    Args:
        flyer_data: Dictionary containing flyer content like:
            - service: Service name/title
            - tagline: Tagline or subtitle
            - description: Main description text
            - features: List of features/bullet points
            - contact: Contact information
            - image_url: Optional header image URL
            - primary_color: Optional hex color for accents
    
    Returns:
        BytesIO buffer containing the PDF
    """
    buffer = BytesIO()
    
    # Letter size (8.5 x 11 inches)
    page_width, page_height = letter
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75*inch,
        rightMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Get primary color
    primary_color_hex = flyer_data.get('primary_color', '#2563eb')
    try:
        primary_color = colors.HexColor(primary_color_hex)
    except:
        primary_color = colors.HexColor('#2563eb')
    
    # Custom styles
    title_style = ParagraphStyle(
        'FlyerTitle',
        parent=styles['Title'],
        fontSize=28,
        textColor=primary_color,
        alignment=TA_CENTER,
        spaceAfter=12
    )
    
    tagline_style = ParagraphStyle(
        'FlyerTagline',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.HexColor('#666666'),
        alignment=TA_CENTER,
        spaceAfter=24,
        fontName='Helvetica-Oblique'
    )
    
    heading_style = ParagraphStyle(
        'FlyerHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=primary_color,
        spaceAfter=8,
        spaceBefore=16
    )
    
    body_style = ParagraphStyle(
        'FlyerBody',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#333333'),
        alignment=TA_LEFT,
        spaceAfter=8,
        leading=16
    )
    
    bullet_style = ParagraphStyle(
        'FlyerBullet',
        parent=body_style,
        leftIndent=20,
        bulletIndent=10
    )
    
    contact_style = ParagraphStyle(
        'FlyerContact',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#333333'),
        alignment=TA_CENTER,
        spaceAfter=6
    )
    
    # Header image if provided
    if flyer_data.get('image_url'):
        try:
            img_response = requests.get(flyer_data['image_url'], timeout=10)
            img_buffer = BytesIO(img_response.content)
            img = Image(img_buffer, width=6*inch, height=3*inch)
            story.append(img)
            story.append(Spacer(1, 12))
        except Exception as e:
            print(f"Failed to load flyer image: {e}")
    
    # Title
    service_name = flyer_data.get('service', 'Our Service')
    story.append(Paragraph(service_name, title_style))
    
    # Tagline
    if flyer_data.get('tagline'):
        story.append(Paragraph(flyer_data['tagline'], tagline_style))
    
    # Description
    if flyer_data.get('description'):
        story.append(Paragraph(flyer_data['description'], body_style))
        story.append(Spacer(1, 12))
    
    # Features
    features = flyer_data.get('features', [])
    if features:
        story.append(Paragraph("What We Offer", heading_style))
        for feature in features:
            if isinstance(feature, str):
                story.append(Paragraph(f"• {feature}", bullet_style))
            elif isinstance(feature, dict):
                feature_text = feature.get('text', feature.get('name', ''))
                story.append(Paragraph(f"• {feature_text}", bullet_style))
    
    # Contact information
    if flyer_data.get('contact'):
        story.append(Spacer(1, 24))
        story.append(Paragraph("Contact Us", heading_style))
        
        contact = flyer_data['contact']
        if isinstance(contact, str):
            story.append(Paragraph(contact, contact_style))
        elif isinstance(contact, dict):
            if contact.get('phone'):
                story.append(Paragraph(f"📞 {contact['phone']}", contact_style))
            if contact.get('email'):
                story.append(Paragraph(f"✉️ {contact['email']}", contact_style))
            if contact.get('website'):
                story.append(Paragraph(f"🌐 {contact['website']}", contact_style))
            if contact.get('address'):
                story.append(Paragraph(f"📍 {contact['address']}", contact_style))
    
    # Build PDF
    doc.build(story)
    
    buffer.seek(0)
    return buffer
