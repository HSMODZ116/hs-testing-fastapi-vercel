# A360 Social Downloader (Vercel)

This is a Vercel-ready FastAPI app exposing only 4 downloaders from A360API:

- Instagram:  GET /insta/dl?url=
- Facebook:   GET /fb/dl?url=
- TikTok:     GET /tik/dl?url=
- Pinterest:  GET /pnt/dl?url=

After deploy, open `/docs` for Swagger UI.

## Deploy
- Push this folder to GitHub
- Import in Vercel and Deploy (Framework: Other)

## Local run
pip install -r requirements.txt
uvicorn api.index:app --reload
