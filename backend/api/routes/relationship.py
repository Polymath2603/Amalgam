"""
Relationship API routes.
"""
import logging 
import re

from fastapi import APIRouter, HTTPException
from backend .api .deps import relationship 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["relationship"])

# Only allow alphanumeric, hyphens, underscores for character IDs
_VALID_CHAR_ID = re.compile(r'^[a-zA-Z0-9_-]+$')


@router .get ("/api/relationship/{character_id}")
async def get_relationship (character_id :str ):
    # Validate character_id to prevent injection
    if not _VALID_CHAR_ID.match(character_id):
        raise HTTPException(status_code=400, detail=f"Invalid character_id: {character_id}")
    stats =await relationship ().get_stats (character_id )
    return {"character_id":character_id ,**stats }
