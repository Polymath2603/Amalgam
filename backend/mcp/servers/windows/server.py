"""
Windows management MCP server — wraps wmctrl + xdotool for X11.

Tools:
  - list_windows()                          List all open windows
  - activate_window(title)                  Focus a window by title substring
  - close_window(title)                     Close a window gracefully
  - move_window(title, x, y)               Move a window to x, y
  - resize_window(title, width, height)     Resize a window
  - maximize_window(title)                  Maximize a window
  - minimize_window(title)                  Minimize (iconify) a window
  - switch_desktop(num)                     Switch to desktop by number (0-based)
"""
import asyncio 
import logging 
from mcp .server import Server 
from mcp .types import Tool ,TextContent 

logger =logging .getLogger (__name__ )

app =Server ("windows-server")


def _run (cmd :str )->str :
    import subprocess 
    try :
        r =subprocess .run (cmd ,shell =True ,capture_output =True ,text =True ,timeout =5 )
        if r .returncode !=0 :
            err =r .stderr .strip ()or f"exit code {r .returncode }"
            raise RuntimeError (err )
        return r .stdout .strip ()
    except RuntimeError :
        raise 
    except Exception as e :
        raise RuntimeError (str (e ))from e 


@app .list_tools ()
async def list_tools ()->list [Tool ]:
    return [
    Tool (
    name ="list_windows",
    description ="List all open windows with their titles and IDs.",
    inputSchema ={"type":"object","properties":{}},
    ),
    Tool (
    name ="activate_window",
    description ="Focus and raise a window by matching its title (substring match).",
    inputSchema ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Window title substring to match"},
    },
    "required":["title"],
    },
    ),
    Tool (
    name ="close_window",
    description ="Close a window gracefully by title substring.",
    inputSchema ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Window title substring to match"},
    },
    "required":["title"],
    },
    ),
    Tool (
    name ="move_window",
    description ="Move a window to the specified screen coordinates.",
    inputSchema ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Window title substring to match"},
    "x":{"type":"integer","description":"Target X coordinate"},
    "y":{"type":"integer","description":"Target Y coordinate"},
    },
    "required":["title","x","y"],
    },
    ),
    Tool (
    name ="resize_window",
    description ="Resize a window to the specified width and height.",
    inputSchema ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Window title substring to match"},
    "width":{"type":"integer","description":"New width in pixels"},
    "height":{"type":"integer","description":"New height in pixels"},
    },
    "required":["title","width","height"],
    },
    ),
    Tool (
    name ="maximize_window",
    description ="Maximize (fullscreen) a window by title substring.",
    inputSchema ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Window title substring to match"},
    },
    "required":["title"],
    },
    ),
    Tool (
    name ="minimize_window",
    description ="Minimize (iconify) a window by title substring.",
    inputSchema ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Window title substring to match"},
    },
    "required":["title"],
    },
    ),
    Tool (
    name ="switch_desktop",
    description ="Switch to a specific desktop/workspace by number (0-based).",
    inputSchema ={
    "type":"object",
    "properties":{
    "num":{"type":"integer","description":"Desktop number (0 = first desktop)"},
    },
    "required":["num"],
    },
    ),
    ]


@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    try :
        if name =="list_windows":
            out =_run ("wmctrl -l")
            if not out :
                return [TextContent (type ="text",text ="No windows found.")]
            lines =["Window ID  | Desktop | Title","-"*60 ]
            for line in out .split ("\n"):
                parts =line .split (None ,3 )
                if len (parts )>=4 :
                    lines .append (f"{parts [0 ]}  | {parts [1 ]}       | {parts [3 ]}")
                else :
                    lines .append (line )
            return [TextContent (type ="text",text ="\n".join (lines ))]

        title =arguments .get ("title","")
        if not title :
            return [TextContent (type ="text",text ="Error: title is required.")]

        if name =="activate_window":
            _run (f"wmctrl -a '{title }'")
            return [TextContent (type ="text",text =f"Activated window matching '{title }'")]

        if name =="close_window":
            _run (f"wmctrl -c '{title }'")
            return [TextContent (type ="text",text =f"Closed window matching '{title }'")]

        if name =="move_window":
            x ,y =arguments .get ("x",0 ),arguments .get ("y",0 )
            _run (f"wmctrl -r '{title }' -e 0,{x },{y },-1,-1")
            return [TextContent (type ="text",text =f"Moved window '{title }' to ({x }, {y })")]

        if name =="resize_window":
            w ,h =arguments .get ("width",0 ),arguments .get ("height",0 )
            _run (f"wmctrl -r '{title }' -e 0,-1,-1,{w },{h }")
            return [TextContent (type ="text",text =f"Resized window '{title }' to {w }x{h }")]

        if name =="maximize_window":
            _run (f"wmctrl -r '{title }' -b toggle,maximized_vert,maximized_horz")
            return [TextContent (type ="text",text =f"Maximized window matching '{title }'")]

        if name =="minimize_window":
            _run (f"xdotool search --name '{title }' windowminimize 2>/dev/null || wmctrl -r '{title }' -b add,hidden")
            return [TextContent (type ="text",text =f"Minimized window matching '{title }'")]

        if name =="switch_desktop":
            num =int (arguments .get ("num",0 ))
            _run (f"wmctrl -s {num }")
            return [TextContent (type ="text",text =f"Switched to desktop {num }")]

        raise ValueError (f"Unknown tool: {name }")
    except RuntimeError as e :
        return [TextContent (type ="text",text =f"Error: {e }")]
    except Exception as e :
        logger .error ("windows tool '%s' failed: %s",name ,e )
        return [TextContent (type ="text",text =f"Error: {e }")]


if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
