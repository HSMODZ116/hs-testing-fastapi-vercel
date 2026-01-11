# A360 Temp Mail API (Vercel Ready)

## Endpoints
- GET /tmail/gen?username=optional&password=optional
  - Creates a mail.tm account + returns token
- GET /tmail/cmail?token=...
  - Checks inbox and returns latest messages (up to 10)

## Deploy
Upload to GitHub, import in Vercel, deploy.

## Notes
This uses https://api.mail.tm as the backend service.
