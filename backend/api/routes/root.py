"""
Root route and static file mounts for the app factory.
Includes the startup event and index route.
"""
import os 
import asyncio 
import logging 

from fastapi import APIRouter 
from fastapi .responses import FileResponse 
from backend .core .paths import FRONTEND_DIR ,VAULT_DIR ,CHARACTERS_DIR ,DATA_DIR 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["root"])


@router .get ("/")
async def index ():
    return FileResponse (os .path .join (str (FRONTEND_DIR ),"index.html"))
