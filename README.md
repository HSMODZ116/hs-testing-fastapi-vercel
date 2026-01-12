# A360 IMG-AI (Gemini) - Vercel Ready

## Setup (Vercel)
Add an environment variable:
- GEMINI_API_KEY = your Google AI Studio key

## Endpoints
- GET  /imgai/ping
- POST /imgai/analysis
- POST /imgai/ocr

### Request body (JSON)
{
  "code": "<base64-image>",
  "mimeType": "image/jpeg",
  "prompt": "optional custom prompt"
}

## Notes
- This project does NOT generate images. It does image analysis + OCR using Gemini.
- Keep your API key private; do not commit it to GitHub.
