"""
Commands API route — GET /api/commands returns available slash commands.
"""
import logging 
from fastapi import APIRouter 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["commands"])


COMMANDS =[
{"name":"clear","desc":"Clear history and start fresh"},
{"name":"new","desc":"Start a new session"},
{"name":"status","desc":"Show current provider, model, and session"},
{"name":"compact","desc":"Force memory compaction"},
{"name":"help","desc":"Show available slash commands"},
{"name":"provider","desc":"Switch AI provider (gemini, ollama, openrouter, etc.)"},
{"name":"model","desc":"Switch model for current provider"},
{"name":"session","desc":"Load or show current session ID"},
]


@router .get ("/api/commands")
async def get_commands ():
    return {"commands":COMMANDS }
