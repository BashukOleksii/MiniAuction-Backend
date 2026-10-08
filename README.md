# Mini Auction Backend

FastAPI + PyMongo Async + MongoDB Atlas + Cloudinary.

## Run locally

1. Python 3.12+; create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   On Linux/macOS: `python3 -m venv .venv && source .venv/bin/activate`.

2. Install dependencies: `python -m pip install -r requirements-dev.txt`.
3. Copy `.env.example` to `.env`, then replace placeholders with credentials.
4. In MongoDB Atlas, create a cluster, an app database user, and a network access entry for your current public IP.
5. Run: `uvicorn app.main:app --reload`.
6. Open http://127.0.0.1:8000/docs. Check GET `/api/v1/health/db`.
7. Run model tests: `pytest -q`.

## Render

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Configure environment variables from `.env.example` in Render dashboard. Do not commit `.env`.
- Configure MongoDB Atlas network access for the Render service.

## Architecture

- `app/models/` — MongoDB document models, currently string UUID `_id`.
- `app/db/` — MongoDB client and indexes.
- `app/core/` — environment settings and Cloudinary configuration.
- `app/api/routes/` — API endpoints.
- `app/repositories/` — future DB access logic.
- `app/services/` — future business rules (atomic bids, auction completion).
- `app/schemas/` — future request and public response DTOs; do not expose user password_hash.

This starter deliberately does not implement registration, image uploading or placing bids yet. Accepting bids needs an atomic transaction across bid history and auction price, including concurrency conflict handling and end-time validation.
