from mcp .server import Server 
from mcp .types import Tool ,TextContent 
import base64 
from io import BytesIO 

app =Server ("screenshot-server")

@app .list_tools ()
async def list_tools ()->list [Tool ]:
    return [
    Tool (
    name ="capture_screen",
    description ="Take a screenshot of the display",
    inputSchema ={
    "type":"object",
    "properties":{}
    }
    )
    ]

@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    if name =="capture_screen":
        try :
            import mss 
            import mss .tools 
            from PIL import Image 

            with mss .mss ()as sct :
                monitor =sct .monitors [1 ]
                sct_img =sct .grab (monitor )
                img =Image .frombytes ("RGB",sct_img .size ,sct_img .bgra ,"raw","BGRX")

                buffered =BytesIO ()
                img .save (buffered ,format ="PNG")
                img_str =base64 .b64encode (buffered .getvalue ()).decode ()

                return [TextContent (type ="text",text =img_str )]
        except ImportError :
            return [TextContent (type ="text",text ="iVBOR... (Mocked screenshot due to missing dependencies)")]

    raise ValueError (f"Unknown tool: {name }")

if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    import asyncio 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
