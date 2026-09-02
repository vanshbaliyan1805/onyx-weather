#  OnyxWeather - National Weather Big Data Platform

This is the containerized local development environment for the OnyxWeather platform. Follow this guide to set up and run the entire system (frontend, backend, ML model, database, and data ingestion pipeline) on any computer.

---

## 💻 Prerequisites (What you need installed)

To run this platform on another computer, you only need the following tools:

1. **Docker Desktop** (Required)
   - **Windows:** Ensure WSL2 (Windows Subsystem for Linux) is enabled.
   - **macOS / Linux:** Standard Docker installation.
2. **Git** (To clone/manage the repository)

*Note: You do NOT need to install Python, PostgreSQL, Node, or Nginx on your host computer. Docker handles all of those automatically.*

---

##  Step-by-Step Setup & Run Guide

### Step 1: Download/Clone the Project
Clone the repository to the local machine:
```bash
git clone <your-repository-url>
cd sih-weather-platform
```

### Step 2: Build and Start the Containers
Run the following command to download/build the Docker images and start the network:
```bash
docker compose up --build
```
This command starts:
- 🖥️ **Frontend:** http://localhost:3000
- ⚙️ **Backend API:** http://localhost:8000 (docs at http://localhost:8000/docs)
- 🧠 **ML Model Service:** http://localhost:8001
- 🗄️ **PostgreSQL Database:** localhost:5432 (DB: `weather_db`, User: `postgres`, Password: `password`)

---

## 🗄️ Step 3: Database & Data Setup (First-time run only)

While the containers are running in your first terminal, open a **new terminal window** in the project folder and run the following setup commands:

### A. Run Database Migrations (Alembic)
This creates the tables and schema in your PostgreSQL database:
```bash
docker compose exec backend alembic upgrade head
```

### B. Initialize Data Ingestion Database Connection
Setup the ingestion script:
```bash
docker compose run data-ingestion python main.py init-db
```

### C. Run Data Ingestion Demo
Populate the database with sample weather, RSS, and social media data to test connections:
```bash
docker compose run data-ingestion python main.py fetch --demo
```

---

## 🔌 System Port Mappings

| Service | Host Port | Container Port | Purpose |
| :--- | :--- | :--- | :--- |
| **Frontend** | `3000` | `80` | Client UI (served by Nginx) |
| **Backend** | `8000` | `8000` | FastAPI application endpoints |
| **ML Model** | `8001` | `8001` | FastAPI machine learning prediction api |
| **Database** | `5432` | `5432` | PostgreSQL database instance |
| **Data Ingestion**| *None* | *None* | CLI tool runs on-demand to fetch data |
