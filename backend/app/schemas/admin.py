from pydantic import BaseModel
from typing import Optional

class AdminVerificationUpdate(BaseModel):
    verification_status: str

class AdminCategoryUpdate(BaseModel):
    event_category: str
