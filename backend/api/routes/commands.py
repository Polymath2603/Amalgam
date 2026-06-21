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
{"name":"resume","desc":"Show last 5 turns of current session"},
{"name":"rename","desc":"Rename current session"},
{"name":"status","desc":"Show provider, model, session"},
{"name":"compact","desc":"Force memory compaction"},
{"name":"help","desc":"Show available slash commands"},
{"name":"provider","desc":"Switch AI provider (gemini, ollama, openrouter, etc.)"},
{"name":"model","desc":"Switch model for current provider"},
{"name":"settings","desc":"Show or set configuration values"},
{"name":"memory","desc":"Show memory stats"},
{"name":"stats","desc":"Show tool usage analytics"},
{"name":"health","desc":"Run live service health checks"},
{"name":"theme","desc":"Switch UI theme (dark, midnight, light, nord)"},
{"name":"character","desc":"Load a character"},
{"name":"profile","desc":"Switch settings profile"},
{"name":"think","desc":"Toggle thinking display on/off"},
{"name":"companion","desc":"Toggle companion mode on/off"},
{"name":"permission","desc":"Set permission level (readonly, confirm, full)"},
]

# Commands are static — cache the response
_CACHED_COMMANDS_RESPONSE = {"commands": COMMANDS}


@router .get ("/api/commands")
async def get_commands ():
    return _CACHED_COMMANDS_RESPONSE
