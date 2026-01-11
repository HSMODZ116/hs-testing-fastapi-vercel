# A360 YT API (Vercel Ready)

This is a minimal deploy bundle extracted from `A360API-main.zip` containing ONLY the YouTube endpoints.

## Endpoints
- GET `/yt/search?query=...`
- GET `/yt/dl?url=...`

## Deploy on Vercel
1. Push this folder to GitHub (or upload to Vercel).
2. In Vercel: New Project -> Import repo -> Deploy.

## Notes
- `/yt/dl` uses `https://www.clipto.com/api/youtube` to fetch download links.
- Logging writes to stdout on Vercel (no log file).
