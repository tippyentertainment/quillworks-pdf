"""
EPUB generation module for converting PDFs to EPUB format.
"""

import requests
from io import BytesIO
from ebooklib import epub
import pdfplumber


def build_epub(
    interior_pdf_url: str,
    title: str,
    author: str,
    cover_pdf_url: str = None,
    description: str = None,
    language: str = 'en'
) -> bytes:
    """
    Build an EPUB from a PDF file.
    
    Args:
        interior_pdf_url: URL to the interior PDF file
        title: Book title
        author: Author name
        cover_pdf_url: Optional URL to cover PDF
        description: Optional book description
        language: Language code (default: 'en')
    
    Returns:
        EPUB file as bytes
    """
    # Create EPUB book
    book = epub.EpubBook()
    
    # Set metadata
    book.set_identifier(f'quillworks-{title.lower().replace(" ", "-")}')
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)
    
    if description:
        book.add_metadata('DC', 'description', description)
    
    # Download and extract cover if provided
    if cover_pdf_url:
        try:
            cover_response = requests.get(cover_pdf_url, timeout=30)
            cover_response.raise_for_status()
            cover_pdf = BytesIO(cover_response.content)
            
            with pdfplumber.open(cover_pdf) as pdf:
                if pdf.pages:
                    # Convert first page to image for cover
                    cover_page = pdf.pages[0]
                    cover_img = cover_page.to_image(resolution=150)
                    
                    img_buffer = BytesIO()
                    cover_img.save(img_buffer, format='PNG')
                    img_buffer.seek(0)
                    
                    book.set_cover('cover.png', img_buffer.getvalue())
        except Exception as e:
            print(f"[EPUB] Failed to extract cover: {e}")
    
    # Download and extract text from interior PDF
    response = requests.get(interior_pdf_url, timeout=60)
    response.raise_for_status()
    pdf_buffer = BytesIO(response.content)
    
    chapters = []
    chapter_content = []
    current_chapter_num = 0
    
    with pdfplumber.open(pdf_buffer) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            
            # Simple chapter detection - look for "Chapter" at start of text
            lines = text.split('\n')
            
            for line in lines:
                stripped = line.strip()
                
                # Check if this looks like a chapter heading
                is_chapter_heading = (
                    stripped.lower().startswith('chapter ') or
                    stripped.lower().startswith('part ') or
                    (len(stripped) < 50 and stripped.isupper() and len(stripped) > 3)
                )
                
                if is_chapter_heading and chapter_content:
                    # Save previous chapter
                    current_chapter_num += 1
                    chapter = create_chapter(
                        current_chapter_num,
                        f"Chapter {current_chapter_num}",
                        '\n'.join(chapter_content)
                    )
                    chapters.append(chapter)
                    book.add_item(chapter)
                    chapter_content = []
                
                chapter_content.append(stripped)
    
    # Add final chapter
    if chapter_content:
        current_chapter_num += 1
        chapter = create_chapter(
            current_chapter_num,
            f"Chapter {current_chapter_num}" if current_chapter_num > 1 else title,
            '\n'.join(chapter_content)
        )
        chapters.append(chapter)
        book.add_item(chapter)
    
    # If no chapters were created, create one with all content
    if not chapters:
        chapter = create_chapter(1, title, "No text content could be extracted from the PDF.")
        chapters.append(chapter)
        book.add_item(chapter)
    
    # Add navigation
    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    # Add CSS
    style = '''
    body { font-family: Georgia, serif; line-height: 1.6; margin: 1em; }
    h1, h2, h3 { font-family: Helvetica, Arial, sans-serif; }
    p { text-indent: 1.5em; margin: 0.5em 0; }
    '''
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style
    )
    book.add_item(nav_css)
    
    # Set spine
    book.spine = ['nav'] + chapters
    
    # Write EPUB to bytes
    output = BytesIO()
    epub.write_epub(output, book, {})
    output.seek(0)
    
    return output.getvalue()


def create_chapter(num: int, title: str, content: str) -> epub.EpubHtml:
    """
    Create an EPUB chapter from text content.
    
    Args:
        num: Chapter number
        title: Chapter title
        content: Text content
    
    Returns:
        EpubHtml chapter object
    """
    chapter = epub.EpubHtml(
        title=title,
        file_name=f'chapter_{num}.xhtml',
        lang='en'
    )
    
    # Convert plain text to HTML paragraphs
    paragraphs = content.split('\n\n')
    html_content = f'<h1>{title}</h1>\n'
    
    for para in paragraphs:
        para = para.strip()
        if para:
            # Escape HTML entities
            para = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_content += f'<p>{para}</p>\n'
    
    chapter.content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>{title}</title>
    <link rel="stylesheet" type="text/css" href="style/nav.css"/>
</head>
<body>
{html_content}
</body>
</html>'''
    
    return chapter
