# Onyx Weather

Onyx Weather is a National Weather Big Data Analytics hackathon project. It collects real-time weather reports from various sources (Open-Meteo, RSS feeds, Mastodon, Citizen Reports), processes them using Machine Learning, and serves them via a robust FastAPI backend.

## Deployment Architecture

The project is designed with a modern, decoupled architecture suitable for both hackathon demonstrations and scalable production deployment:

```mermaid
graph TD
    A[Frontend] -->|HTTPS / REST API| B(FastAPI Backend Hosted on Render)
    C[Data Ingestion Pipeline] -->|psycopg2| D[(Supabase PostgreSQL)]
    B <-->|SQLAlchemy Async| D
    B <-->|ML Classification| E[ML Service/Logic]
```

### 1. PostgreSQL Database (Hosted on Supabase)
We use a **shared PostgreSQL database** hosted on Supabase.
- The **Data Ingestion Team** runs their Python pipeline locally or via a cron job, writing data directly to this Supabase PostgreSQL instance using `psycopg2`.
- The **Backend Team** connects to this exact same database using `SQLAlchemy` (AsyncPG) to read and serve the data.

### 2. FastAPI Backend (Hosted on Render)
The backend is a FastAPI application that will be deployed on Render as a Web Service.
- It exposes REST APIs for the frontend.
- It handles ML categorization and confidence scoring.
- Connection pooling is optimized so that Render won't overwhelm the Supabase instance.

### 3. Frontend
The frontend (Vercel/Netlify/Render) communicates **exclusively** with the FastAPI backend over HTTPS. It never talks directly to the database.

---

## Local Development Setup

### 1. Database Setup
1. Create a local PostgreSQL database (e.g., `weather_db`).
2. Run the backend migrations to create the tables:
   ```bash
   cd backend
   python -m venv venv
   venv\Scripts\activate  # (or source venv/bin/activate on Mac/Linux)
   pip install -r requirements.txt
   
   # Setup .env file
   cp .env.example .env
   # Edit .env with your local DB URL: postgresql+asyncpg://user:password@localhost:5432/weather_db
   
   alembic upgrade head
   ```

### 2. Running Data Ingestion
The ingestion pipeline has been updated to write to PostgreSQL.
```bash
cd data/ingestion_pipeline
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Run a demo fetch
python main.py fetch --demo
```
*(Note: It will automatically load the `DATABASE_URL` from the backend's `.env` file for local development!)*

### 3. Running the Backend
```bash
cd backend
venv\Scripts\activate
uvicorn main:app --reload
```
Check `http://localhost:8000/docs` to see the Swagger UI.

---

## Production Deployment Guide

### Hosting the Database on Supabase
1. Create a project on [Supabase](https://supabase.com).
2. Go to Project Settings -> Database and copy the **Connection string (URI)**.
3. Make sure to use the **Transaction pooler** port (`6543`) for scalable connections!
4. The URL looks like: `postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`

### Hosting the Backend on Render
1. Create a **Web Service** on [Render](https://render.com).
2. Connect this GitHub repository.
3. Use the following settings (pre-configured in `render.yaml`):
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment Variables**:
   - `DATABASE_URL`: Add your Supabase URI (Replace `postgresql://` with `postgresql+asyncpg://`).
   - `FRONTEND_ORIGINS`: Add the URL of your deployed frontend (e.g., `https://my-frontend.vercel.app`).
   - `OPENAI_API_KEY`: Add your API key for ML processing.
5. Deploy! Render will automatically give you a secure `https://...onrender.com` URL.

---

## Important Rules for the Team
- **Do NOT commit passwords or API keys to GitHub.** Use `.env` files locally and Environment Variables in Render/Supabase.
- **Do NOT change the ingestion database schema.** The data ingestion team writes to the `weather_reports` table using raw SQL. If you change columns in FastAPI, you will break their pipeline!
- **Run `alembic upgrade head`** whenever you pull new code to ensure your local DB matches the required schema.
