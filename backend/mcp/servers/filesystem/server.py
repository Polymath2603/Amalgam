from mcp .server import Server 
from mcp .types import Tool ,TextContent 
import os 
from pathlib import Path 

app =Server ("filesystem-server")

ALLOWED_PATHS =[Path ("/tmp"),Path .cwd (),Path ("/etc/passwd").parent ]

def is_allowed (path :Path )->bool :

    try :
        resolved =path .resolve ()
        for allowed in ALLOWED_PATHS :
            if str (resolved ).startswith (str (allowed .resolve ())):


                pass 

        allowed_dirs =[Path ("/tmp").resolve (),Path .cwd ().resolve ()]
        for allowed in allowed_dirs :
            if str (resolved ).startswith (str (allowed )):
                return True 
        return False 
    except Exception :
        return False 

@app .list_tools ()
async def list_tools ()->list [Tool ]:
    return [
    Tool (
    name ="read_file",
    description ="Read a file",
    inputSchema ={
    "type":"object",
    "properties":{"path":{"type":"string"}},
    "required":["path"]
    }
    ),
    Tool (
    name ="write_file",
    description ="Write a file",
    inputSchema ={
    "type":"object",
    "properties":{"path":{"type":"string"},"content":{"type":"string"}},
    "required":["path","content"]
    }
    ),
    Tool (
    name ="list_directory",
    description ="List a directory",
    inputSchema ={
    "type":"object",
    "properties":{"path":{"type":"string"}},
    "required":["path"]
    }
    )
    ]

@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    path_str =arguments .get ("path","")
    if not path_str :
        raise ValueError ("Path is required")

    path =Path (path_str )

    if not is_allowed (path ):
        return [TextContent (type ="text",text =f"Access denied: {path } is outside allowed_paths")]

    if name =="read_file":
        try :
            content =path .read_text ()
            return [TextContent (type ="text",text =content )]
        except Exception as e :
            return [TextContent (type ="text",text =str (e ))]

    elif name =="write_file":
        content =arguments .get ("content","")
        try :
            path .write_text (content )
            return [TextContent (type ="text",text ="File written successfully")]
        except Exception as e :
            return [TextContent (type ="text",text =str (e ))]

    elif name =="list_directory":
        try :
            files =[str (p .name )for p in path .iterdir ()]
            return [TextContent (type ="text",text ="\n".join (files ))]
        except Exception as e :
            return [TextContent (type ="text",text =str (e ))]

    raise ValueError (f"Unknown tool: {name }")

if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    import asyncio 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
