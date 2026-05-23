from mcp .server import Server 
from mcp .types import Tool ,TextContent 
import subprocess 
import asyncio 
import os 
import shlex 

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
"whoami","uname",
]

if ALLOWED_PREFIXES_ENV :
    ALLOWED_PREFIXES =[p .strip ()+" "if not p .strip ().endswith (" ")else p .strip ()for p in ALLOWED_PREFIXES_ENV .split (",")]
else :
    ALLOWED_PREFIXES =_DEFAULT_ALLOWED 

def _is_allowed (cmd :str )->bool :
    if SHELL_MODE =="unrestricted":
        return True 
    trimmed =cmd .lstrip ()
    for prefix in ALLOWED_PREFIXES :
        if trimmed ==prefix .strip ()or trimmed .startswith (prefix ):
            return True 
    return False 

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
    )
    ]

@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    if name =="execute_command":
        cmd =arguments .get ("cmd")
        if not cmd :
            raise ValueError ("Command is required")

        if not _is_allowed (cmd ):
            return [TextContent (type ="text",text =f"Command not allowed (mode={SHELL_MODE }): {cmd }")]

        process =await asyncio .create_subprocess_shell (
        cmd ,
        stdout =asyncio .subprocess .PIPE ,
        stderr =asyncio .subprocess .PIPE 
        )
        stdout ,stderr =await process .communicate ()
        result =stdout .decode ()
        if stderr :
            result +="\n"+stderr .decode ()
        return [TextContent (type ="text",text =result )]
    raise ValueError (f"Unknown tool: {name }")

if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
