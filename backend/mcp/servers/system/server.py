from mcp .server import Server 
from mcp .types import Tool ,TextContent 
import asyncio 
import os 
import shlex 

app =Server ("system-server")


@app .list_tools ()
async def list_tools ()->list [Tool ]:
    return [
    Tool (
    name ="get_cpu_usage",
    description ="Get current CPU usage percentage",
    inputSchema ={"type":"object","properties":{}},
    ),
    Tool (
    name ="get_memory_usage",
    description ="Get current memory usage (total, used, free, percent)",
    inputSchema ={"type":"object","properties":{}},
    ),
    Tool (
    name ="get_running_processes",
    description ="List running processes by CPU usage",
    inputSchema ={
    "type":"object",
    "properties":{
    "count":{"type":"integer","description":"Number of processes to show (default: 10)"},
    },
    },
    ),
    Tool (
    name ="get_clipboard",
    description ="Get the current clipboard content",
    inputSchema ={"type":"object","properties":{}},
    ),
    Tool (
    name ="set_clipboard",
    description ="Set the clipboard content",
    inputSchema ={
    "type":"object",
    "properties":{
    "text":{"type":"string","description":"Text to set in clipboard"},
    },
    "required":["text"],
    },
    ),
    Tool (
    name ="get_current_time",
    description ="Get the current system date and time",
    inputSchema ={"type":"object","properties":{}},
    ),
    Tool (
    name ="set_reminder",
    description ="Set a reminder that logs after a delay",
    inputSchema ={
    "type":"object",
    "properties":{
    "text":{"type":"string","description":"Reminder message"},
    "delay_seconds":{"type":"integer","description":"Delay in seconds"},
    },
    "required":["text","delay_seconds"],
    },
    ),
    ]


@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    if name =="get_cpu_usage":
        try :
            proc =await asyncio .create_subprocess_exec (
            "python3","-c","import psutil; print(psutil.cpu_percent(interval=0.5))",
            stdout =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
            )
            stdout ,stderr =await proc .communicate ()
            if stdout :
                return [TextContent (type ="text",text =f"CPU: {stdout .decode ().strip ()}%")]
            return [TextContent (type ="text",text =f"CPU: unavailable ({stderr .decode ().strip ()})")]
        except Exception as e :
            return [TextContent (type ="text",text =f"Error: {e }")]

    elif name =="get_memory_usage":
        try :
            proc =await asyncio .create_subprocess_exec (
            "python3","-c",(
            "import psutil; m=psutil.virtual_memory(); "
            "print(f'Total: {m.total//1024//1024}MB, Used: {m.used//1024//1024}MB, "
            "Free: {m.available//1024//1024}MB, Percent: {m.percent}%')"
            ),
            stdout =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
            )
            stdout ,stderr =await proc .communicate ()
            if stdout :
                return [TextContent (type ="text",text =stdout .decode ().strip ())]
            return [TextContent (type ="text",text =f"Memory: unavailable ({stderr .decode ().strip ()})")]
        except Exception as e :
            return [TextContent (type ="text",text =f"Error: {e }")]

    elif name =="get_running_processes":
        count =int (arguments .get ("count",10 ))
        try :
            proc =await asyncio .create_subprocess_exec (
            "ps","aux","--sort=-%cpu",
            stdout =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
            )
            stdout ,stderr =await proc .communicate ()
            lines =stdout .decode ().splitlines ()
            if lines :
                header =lines [0 ]
                top =lines [1 :1 +count ]
                result =header +"\n"+"\n".join (top )
                return [TextContent (type ="text",text =result )]
            return [TextContent (type ="text",text ="No processes found")]
        except Exception as e :
            return [TextContent (type ="text",text =f"Error: {e }")]

    elif name =="get_clipboard":
        try :
            for tool in ("xclip","wl-paste","pbpaste","termux-clipboard-get"):
                if tool =="xclip":
                    proc =await asyncio .create_subprocess_exec (
                    "xclip","-o","-selection","clipboard",
                    stdout =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
                    )
                elif tool =="wl-paste":
                    proc =await asyncio .create_subprocess_exec (
                    "wl-paste",
                    stdout =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
                    )
                elif tool =="pbpaste":
                    proc =await asyncio .create_subprocess_exec (
                    "pbpaste",
                    stdout =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
                    )
                else :
                    continue 
                stdout ,stderr =await proc .communicate ()
                if proc .returncode ==0 and stdout :
                    text =stdout .decode ().strip ()
                    return [TextContent (type ="text",text =text [:2000 ]or "(empty clipboard)")]
            return [TextContent (type ="text",text ="Clipboard: no supported tool found (install xclip or wl-clipboard)")]
        except Exception as e :
            return [TextContent (type ="text",text =f"Error: {e }")]

    elif name =="set_clipboard":
        text =arguments .get ("text","")
        try :
            for tool in ("xclip","wl-copy"):
                if tool =="xclip":
                    proc =await asyncio .create_subprocess_exec (
                    "xclip","-i","-selection","clipboard",
                    stdin =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
                    )
                else :
                    proc =await asyncio .create_subprocess_exec (
                    "wl-copy",
                    stdin =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
                    )
                stdout ,stderr =await proc .communicate (input =text .encode ())
                if proc .returncode ==0 :
                    return [TextContent (type ="text",text =f"Clipboard set ({len (text )} chars)")]
            return [TextContent (type ="text",text ="Clipboard: no supported tool found (install xclip or wl-clipboard)")]
        except Exception as e :
            return [TextContent (type ="text",text =f"Error: {e }")]

    elif name =="get_current_time":
        proc =await asyncio .create_subprocess_exec (
        "date",
        stdout =asyncio .subprocess .PIPE ,stderr =asyncio .subprocess .PIPE ,
        )
        stdout ,stderr =await proc .communicate ()
        return [TextContent (type ="text",text =stdout .decode ().strip ()or f"Error: {stderr .decode ().strip ()}")]

    elif name =="set_reminder":
        text =arguments .get ("text","")
        delay =int (arguments .get ("delay_seconds",60 ))

        async def _fire ():
            await asyncio .sleep (delay )
            logger = logging.getLogger(__name__)
            logger.warning(f"REMINDER: {text}")

        asyncio .create_task (_fire ())
        return [TextContent (type ="text",text =f"Reminder set: \"{text }\" in {delay }s")]

    raise ValueError (f"Unknown tool: {name }")


if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
