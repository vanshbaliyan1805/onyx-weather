from app.database import Base
from app.models.weather_report import WeatherReport

# Export models for Alembic
__all__ = ["Base", "WeatherReport"]
