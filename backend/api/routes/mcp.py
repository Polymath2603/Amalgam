"""
MCP (Model Context Protocol) API routes.
"""
import logging 

from fastapi import APIRouter 
from backend .api .deps import settings ,mcp 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["mcp"])


@router .get ("/api/mcp/servers")
async def get_mcp_servers ():
    """Get configured MCP servers and their status."""
    servers =settings ().get_mcp_servers ()
    connected =list (mcp ().sessions .keys ())if mcp ()else []
    result =[]
    for s in servers :
        result .append ({
        **s ,
        "connected":s ["name"]in connected 
        })
    return {"servers":result }


@router .post ("/api/mcp/servers")
async def update_mcp_servers (body :dict ):
    """Update MCP server configuration."""
    servers =body .get ("servers",[])
    settings ().set ("mcp.servers",servers )
    return {"status":"ok","message":"MCP settings saved. Restart to apply changes."}


@router .get ("/api/mcp/tools")
async def get_mcp_tools ():
    """Get all available MCP tools."""
    tools =mcp ().get_tool_schema ()if mcp ()else []
    return {"tools":tools }


@router .post ("/api/shell/approve")
async def approve_command (body :dict ):
    """Approve a previously blocked shell command.
    
    Body:
      cmd: str — the exact command that was blocked
      mode: str — "once" | "prefix" | "exact"
    
    Adds the command to the shell server's in-memory allowlist
    via the approve_command MCP tool, and persists to settings.
    """
    cmd =body .get ("cmd","")
    mode =body .get ("mode","once")
    if not cmd :
        return {"status":"error","message":"cmd is required"}

    if mode in ("prefix","exact")and mcp ():
        tool_name ="approve_command"
        if tool_name in mcp ().server_tool_map :
            try :
                await mcp ().call_tool (tool_name ,{"cmd":cmd ,"mode":mode })
            except Exception as e :
                logger .error (f"Failed to approve command via MCP: {e }")

    if mode =="prefix":
        prefix =cmd .lstrip ().split ()[0 ]+" "if " "in cmd .lstrip ()else cmd .lstrip ()
        current =settings ().get ("shell.allowed_prefixes",[])
        if prefix not in current :
            current .append (prefix )
            settings ().set ("shell.allowed_prefixes",current )
    elif mode =="exact":
        current =settings ().get ("shell.allowed_prefixes",[])
        if cmd not in current :
            current .append (cmd )
            settings ().set ("shell.allowed_prefixes",current )

    return {"status":"ok","mode":mode ,"cmd":cmd }
