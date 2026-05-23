"""
Backward-compatible re-export of the FastAPI app.
The application has been split into modules under backend/api/routes/ and backend/api/ws/.
"""
import sys 
import os 

sys .path .insert (0 ,os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ )))))

from backend .app import app 

__all__ =["app"]
