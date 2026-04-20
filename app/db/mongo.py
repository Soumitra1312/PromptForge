# MongoDB async client
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

mongo_client = AsyncIOMotorClient(settings.DATABASE_URL)
db = mongo_client["promptdb"]
