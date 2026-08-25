# Onyx Weather Backend

This is the FastAPI backend for the National Weather Big Data Analytics Platform. It serves as the central hub between the Data Ingestion Pipeline, the Machine Learning service, and the Frontend dashboard.

## Features
- **PostgreSQL & SQLAlchemy**: Scalable storage with an async driver (`asyncpg`).
- **REST APIs**: Core weather APIs with filtering and pagination.
- **Analytics APIs**: Endpoints designed specifically to power frontend charts and dashboards.
- **ML Integration**: Endpoints for the ML service to fetch pending records and submit inference predictions.
- **Admin**: Basic API key-protected endpoints for moderation and verification.

## Architecture

`Data Ingestion -> PostgreSQL <-> FastAPI Backend <-> ML Service & Frontend`

*(Note: Data ingestion pipeline is assumed to be running independently and continuously writing to the database).*

## Setup

1. **Install Dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configuration**
   Copy `.env.example` to `.env` and configure your database string.

3. **Database Migration**
   Ensure PostgreSQL is running.
   ```bash
   alembic upgrade head
   ```
   *(Note: The initial migration script can be generated using `alembic revision --autogenerate -m "Init"` once the DB is up).*

4. **Run Server**
   ```bash
   uvicorn main:app --reload
   ```

5. **Swagger Documentation**
   Open http://localhost:8000/docs for the auto-generated API specifications.

## Docker

Build and run using Docker:
```bash
docker build -t onyx-weather-backend .
docker run -p 8000:8000 --env-file .env onyx-weather-backend
```
