# QuillWorks PDF Generation Service

Simple Flask service for generating PDFs from book data.

## Quick Deploy

### Railway
1. Create new project on Railway
2. Deploy from GitHub or upload this folder
3. Railway will auto-detect Python and use the Procfile
4. Copy the deployment URL (e.g., `https://your-app.railway.app`)
5. Add to Cloudflare Workers secrets:
   - `PDF_SERVICE_URL` = `https://your-app.railway.app`

### Render
1. Create new Web Service
2. Connect your repo or upload folder
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app`
5. Copy the deployment URL
6. Add to Cloudflare Workers secrets

### Fly.io
```bash
fly launch
fly deploy
fly info  # Get the URL
```

## Local Development

```bash
pip install -r requirements.txt
python app.py
```

Test endpoint:
```bash
curl http://localhost:5000/health
```

## API Endpoints

### POST /generate-book-pdf
Generates PDF for regular books

Request body:
```json
{
  "data": {
    "book_title": "My Book",
    "author_name": "Author Name",
    "genre": "Fiction",
    "chapters": [
      {
        "number": 1,
        "title": "Chapter Title",
        "content": "Chapter text..."
      }
    ],
    "trim_size": "6x9",
    "font_size": 11,
    "page_color": "cream"
  }
}
```

### POST /generate-childrens-book-pdf
Generates PDF for children's books with 8.5x11 pages

Request body:
```json
{
  "data": {
    "title": "My Story",
    "author_name": "Author",
    "pages": [
      {
        "text": "Page text",
        "illustration_prompt": "...",
        "image_url": "https://..."
      }
    ]
  }
}
```

Returns: PDF file as binary stream

## Optional: Bembo Font Support

To use Bembo font (for children's books), add Bembo font files to `fonts/` directory:
- `fonts/Bembo.ttf`
- `fonts/Bembo-Italic.ttf`
- `fonts/Bembo-Bold.ttf`

Service will fallback to Times-Roman if fonts are not available.
