from mcp .server import Server 
from mcp .types import Tool ,TextContent 
import subprocess 
import asyncio 

app =Server ("shell-server")

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


        allowed_prefixes =["echo ","ls ","cat ","pwd","date"]
        is_safe =any (cmd .startswith (prefix )or cmd ==prefix .strip ()for prefix in allowed_prefixes )

        if not is_safe :
            return [TextContent (type ="text",text =f"Command not allowed: {cmd }")]

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
