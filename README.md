# Tradematic

Algorithmic trading SaaS platform with a Streamlit member dashboard and FastAPI backend.

## Streamlit Community Cloud

The deployed Streamlit entrypoint is `streamlit_app.py`, which loads the real app from `app.py`.

Set this secret in Streamlit Community Cloud when your FastAPI backend is hosted externally:

```toml
TRADEMATIC_API_URL = "https://your-backend-domain.com"
```

Community Cloud does not run a separate FastAPI backend service for this app. For production, deploy `backend/` on a VPS, Render, Railway, Fly.io, AWS, or another API host, then point `TRADEMATIC_API_URL` to that backend.

## Local Setup

1. Create and activate a Python virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Copy backend environment settings:

```powershell
Copy-Item backend\.env.example backend\.env
```

4. Update `backend\.env` with local secrets and broker settings.
5. Start the FastAPI backend:

```powershell
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

6. Start the Streamlit frontend:

```powershell
streamlit run streamlit_app.py --server.port 8502
```

## Security Notes

- Do not commit `.env` files.
- Store API keys, broker secrets, and app secrets only in environment variables or Streamlit secrets.
- The local SQLite database is ignored by Git.
