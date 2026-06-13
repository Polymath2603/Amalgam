from mcp .server import Server 
from mcp .types import Tool ,TextContent 
import asyncio 
import os 
import shlex 
import json 
import logging 

logger =logging .getLogger (__name__ )

SHELL_TIMEOUT =int (os .environ .get ("AMALGAM_SHELL_TIMEOUT","30"))

app =Server ("shell-server")

SHELL_MODE =os .environ .get ("AMALGAM_SHELL_MODE","safe").lower ()
ALLOWED_PREFIXES_ENV =os .environ .get ("AMALGAM_SHELL_ALLOWED_COMMANDS","")

_DEFAULT_ALLOWED =[
"echo ","ls ","cat ","pwd","date",
"find ","grep ","head ","tail ","wc ",
"mkdir ","cp ","mv ","rm ","touch ",
"curl ","wget ",
"python3 ","python ",
"pip ","pip3 ",
"git status","git log","git diff",
"whoami","uname","notify-send",
"ps ","top ","htop ",
"df ","du ","free ",
"which ","type ",
"kill ","pkill ",
"xdotool ","xclip ","wl-paste ",
]

if ALLOWED_PREFIXES_ENV :
    ALLOWED_PREFIXES =[p .strip ()+" "if not p .strip ().endswith (" ")else p .strip ()for p in ALLOWED_PREFIXES_ENV .split (",")]
else :
    ALLOWED_PREFIXES =list (_DEFAULT_ALLOWED )

ALLOWED_EXACT =set ()
ALLOWED_ONCE =set ()

_APPROVED_EXACT =set ()


def _is_allowed (cmd :str )->tuple [bool ,str ]:
    """Returns (allowed, reason). reason is empty if allowed."""
    if SHELL_MODE =="unrestricted":
        return True ,""
    trimmed =cmd .lstrip ()
    if trimmed in ALLOWED_EXACT or trimmed in _APPROVED_EXACT :
        return True ,""
    for prefix in ALLOWED_PREFIXES :
        if trimmed ==prefix .strip ()or trimmed .startswith (prefix ):
            return True ,""
    return False ,f"COMMAND_BLOCKED:{cmd }"


def _extract_prefix (cmd :str )->str :
    """Get the prefix for a command (first word + space, or the whole command if no args)."""
    trimmed =cmd .lstrip ()
    parts =shlex .split (trimmed )
    if not parts :
        return ""
    if len (parts )==1 :
        return parts [0 ]
    return parts [0 ]+" "


@app .list_tools ()
async def list_tools ()->list [Tool ]:
    return [
    Tool (
    name ="execute_command",
    description ="Execute a shell command",
    inputSchema ={
    "type":"object",
    "properties":{
    "cmd":{"type":"string","description":"The command to execute"}
    },
    "required":["cmd"]
    }
    ),
    Tool (
    name ="approve_command",
    description ="Approve a previously blocked command (call this when user allows it)",
    inputSchema ={
    "type":"object",
    "properties":{
    "cmd":{"type":"string","description":"The exact command to approve"},
    "mode":{"type":"string","description":"once|prefix|exact","default":"once"}
    },
    "required":["cmd"]
    }
    ),
    ]


@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    if name =="execute_command":
        cmd =arguments .get ("cmd")
        if not cmd :
            raise ValueError ("Command is required")

        allowed ,reason =_is_allowed (cmd )
        if not allowed :
            return [TextContent (type ="text",text =reason )]

        # SECURITY: Parse with shlex and use exec instead of shell
        # This prevents command injection via ;, &&, ||, etc.
        try:
            args = shlex.split(cmd)
        except ValueError as e:
            return [TextContent(type="text", text=f"Invalid command syntax: {e}")]

        if not args:
            return [TextContent(type="text", text="Empty command")]

        process = await asyncio.create_subprocess_exec(
            args[0], *args[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try :
            stdout ,stderr =await asyncio .wait_for (process .communicate (),timeout =SHELL_TIMEOUT )
        except asyncio .TimeoutError :
            try :
                process .kill ()
            except Exception :
                pass 
            return [TextContent (type ="text",text =f"Command timed out after {SHELL_TIMEOUT }s: {cmd }")]
        result =stdout .decode ()
        if stderr :
            stderr_text =stderr .decode ().strip ()
            if stderr_text :
                result +="\n[stderr]\n"+stderr_text 
        if process .returncode ==0 and not result .strip ():
            result ="[Command completed successfully with no output.]"
        elif process .returncode !=0 :
            logger .warning (f"Shell command exited with code {process .returncode }: {cmd [:100 ]}")
        return [TextContent (type ="text",text =result )]

    elif name =="approve_command":
        cmd =arguments .get ("cmd","")
        mode =arguments .get ("mode","once")
        trimmed =cmd .lstrip ()
        if mode =="once":
            ALLOWED_ONCE .add (trimmed )
            _APPROVED_EXACT .add (trimmed )
            return [TextContent (type ="text",text =f"Approved once: {cmd }")]
        elif mode =="prefix":
            prefix =_extract_prefix (cmd )
            if prefix and prefix not in ALLOWED_PREFIXES :
                ALLOWED_PREFIXES .append (prefix )
            return [TextContent (type ="text",text =f"Approved command prefix: {prefix } (from: {cmd })")]
        elif mode =="exact":
            _APPROVED_EXACT .add (trimmed )
            ALLOWED_EXACT .add (trimmed )
            return [TextContent (type ="text",text =f"Approved exact command: {cmd }")]
        return [TextContent (type ="text",text =f"Unknown mode: {mode }")]

    raise ValueError (f"Unknown tool: {name }")


if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
