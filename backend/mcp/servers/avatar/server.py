"""
Avatar control MCP server — replaces embedded tag system for emotion/expression/action.
The AI uses these tools instead of embedding /[[emotion]] /((expression)) /**action**/ tags.
Supports per-session state via session_id parameter.
"""
import asyncio 
import json 
import logging 
from mcp .server import Server 
from mcp .types import Tool ,TextContent 

logger =logging .getLogger (__name__ )

app =Server ("avatar-server")

# Per-session state: dict[session_id, dict]
_sessions: dict[str, dict] = {}

def _get_state(session_id: str = "default") -> dict:
    """Get or create avatar state for a session."""
    if session_id not in _sessions:
        _sessions[session_id] = {"emotion": "neutral", "expression": "neutral", "action": None}
    return _sessions[session_id]


@app .list_tools ()
async def list_tools ()->list [Tool ]:
    return [
    Tool (
    name ="avatar_set_emotion",
    description ="Set the TTS voice emotion. Affects speaking tone (happy, sad, angry, surprised, etc). Use this INSTEAD of /[[emotion]] tags.",
    inputSchema ={
    "type":"object",
    "properties":{
    "emotion":{
    "type":"string",
    "description":"Emotion for the voice: happy, sad, angry, surprised, thinking, relaxed, confused, shy, jealous, bored, suspicious, victory, sleep, love, excited",
    "enum":[
    "happy","sad","angry","surprised","thinking",
    "relaxed","confused","shy","jealous","bored",
    "suspicious","victory","sleep","love","excited"
    ]
    },
    "session_id":{
    "type":"string",
    "description":"Optional session identifier for isolated state",
    }
    },
    "required":["emotion"],
    },
    ),
    Tool (
    name ="avatar_set_expression",
    description ="Set the VRM avatar facial expression (blend shape). Controls the avatar's face independently of voice emotion. Use INSTEAD of /((expression)) tags.",
    inputSchema ={
    "type":"object",
    "properties":{
    "expression":{
    "type":"string",
    "description":"Facial expression: happy, angry, sad, relaxed, surprised, blink",
    "enum":["happy","angry","sad","relaxed","surprised","blink"]
    },
    "session_id":{
    "type":"string",
    "description":"Optional session identifier for isolated state",
    }
    },
    "required":["expression"],
    },
    ),
    Tool (
    name ="avatar_perform_action",
    description ="Trigger a full-body VRM animation/gesture. Describe the action naturally (bow, wave, nod, consider, etc). Use INSTEAD of /**action**/ tags.",
    inputSchema ={
    "type":"object",
    "properties":{
    "action":{
    "type":"string",
    "description":"Description of the physical action/gesture (e.g. 'nods thoughtfully', 'waves excitedly', 'bows deeply')"
    },
    "session_id":{
    "type":"string",
    "description":"Optional session identifier for isolated state",
    }
    },
    "required":["action"],
    },
    ),
    Tool (
    name ="avatar_set_visibility",
    description ="Show or hide the avatar overlay window. Use this proactively when arriving or leaving.",
    inputSchema ={
    "type":"object",
    "properties":{
    "visible":{
    "type":"boolean",
    "description":"True to show the avatar, False to hide it"
    },
    "session_id":{
    "type":"string",
    "description":"Optional session identifier for isolated state",
    }
    },
    "required":["visible"],
    },
    ),
    ]


@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    try :
        session_id = arguments.get("session_id", "default")
        state = _get_state(session_id)

        if name =="avatar_set_emotion":
            emotion =arguments .get ("emotion","neutral")
            state ["emotion"]=emotion 
            return [TextContent (type ="text",text =json .dumps ({"type":"emotion","emotion":emotion, "session_id": session_id}))]

        if name =="avatar_set_expression":
            expression =arguments .get ("expression","neutral")
            state ["expression"]=expression 
            return [TextContent (type ="text",text =json .dumps ({"type":"expression","expression":expression, "session_id": session_id}))]

        if name =="avatar_perform_action":
            action =arguments .get ("action","")
            state ["action"]=action 
            return [TextContent (type ="text",text =json .dumps ({"type":"roleplay","action":action, "session_id": session_id}))]

        if name =="avatar_set_visibility":
            visible =arguments .get ("visible",True )
            return [TextContent (type ="text",text =json .dumps ({"type":"visibility","visible":visible, "session_id": session_id}))]

        raise ValueError (f"Unknown tool: {name }")
    except asyncio.CancelledError:
        raise
    except Exception as e :
        logger .error ("avatar tool '%s' failed: %s",name ,e )
        return [TextContent (type ="text",text =f"Error: {e }")]


if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
