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
{"name":"rename","desc":"Rename current session"},
{"name":"export","desc":"Export conversation to markdown file"},
{"name":"sessions","desc":"List all sessions"},
{"name":"session","desc":"Load or show current session ID"},
{"name":"status","desc":"Show provider, model, session, profile"},
{"name":"compact","desc":"Force memory compaction"},
{"name":"help","desc":"Show available slash commands"},
{"name":"provider","desc":"Switch AI provider (gemini, ollama, openrouter, etc.)"},
{"name":"model","desc":"Switch model for current provider"},
{"name":"settings","desc":"Show or set configuration values"},
{"name":"memory","desc":"Show memory stats"},
{"name":"stats","desc":"Show tool usage analytics"},
{"name":"theme","desc":"Switch UI theme (dark, midnight, light, nord)"},
{"name":"character","desc":"Load a character"},
{"name":"profile","desc":"Switch settings profile"},
{"name":"think","desc":"Toggle thinking display on/off"},
{"name":"companion","desc":"Toggle companion mode on/off"},
{"name":"approve","desc":"Approve a tool for one use"},
{"name":"permission","desc":"Set permission level (readonly, confirm, full)"},
]


@router .get ("/api/commands")
async def get_commands ():
    return {"commands":COMMANDS }
