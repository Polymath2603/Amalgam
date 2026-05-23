"""
Relationship API routes.
"""
import logging 

from fastapi import APIRouter 
from backend .api .deps import relationship 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["relationship"])


@router .get ("/api/relationship/{character_id}")
async def get_relationship (character_id :str ):
    stats =relationship ().get_stats (character_id )
    return {"character_id":character_id ,**stats }
