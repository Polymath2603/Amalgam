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
