"""ORM model package — import all models so Alembic can discover them."""

from app.models.bay import Bay  # noqa: F401
from app.models.bay_occupancy import BayOccupancy  # noqa: F401
from app.models.bay_occupancy_history import BayOccupancyHistory  # noqa: F401
from app.models.sensor_reading import SensorReading  # noqa: F401

__all__ = ["Bay", "BayOccupancy", "BayOccupancyHistory", "SensorReading"]
