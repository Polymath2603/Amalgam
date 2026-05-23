"""
Central path definitions.
All modules import from here instead of computing paths themselves.
"""
import os 
from pathlib import Path 

PROJECT_ROOT =Path (os .path .abspath (os .path .join (os .path .dirname (__file__ ),"..")))

DATA_DIR =Path (os .environ .get ("AMALGAM_DATA_DIR",str (PROJECT_ROOT /"user_data")))

CHARACTERS_DIR =Path (os .environ .get ("AMALGAM_CHARACTERS_DIR",str (PROJECT_ROOT /"characters")))
VAULT_DIR =DATA_DIR /"vault"
FRONTEND_DIR =PROJECT_ROOT /"frontend"

SETTINGS_PATH =str (DATA_DIR /"settings.json")
CONVERSATIONS_DB =str (DATA_DIR /"conversations.db")
RELATIONSHIP_DB =str (DATA_DIR /"relationship.db")
