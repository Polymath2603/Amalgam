from mcp .server import Server 
from mcp .types import Tool ,TextContent 
import asyncio 
import os 
import shlex 
import logging
from datetime import datetime, timezone

logger =logging .getLogger (__name__ )

app =Server ("system-server")

# Module-level set for tracking reminder tasks
_reminder_tasks: dict[str, asyncio.Task] = {}


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
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            return [TextContent (type ="text",text =f"CPU: {cpu}%")]
        except ImportError:
            # Fallback to /proc/loadavg
            try:
                with open("/proc/loadavg") as f:
                    load = f.read().strip()
                return [TextContent(type="text", text=f"CPU load: {load}")]
            except Exception as e2:
                return [TextContent(type="text", text=f"CPU: unavailable ({e2})")]
        except Exception as e :
            return [TextContent (type ="text",text =f"Error: {e }")]

    elif name =="get_memory_usage":
        try :
            import psutil
            m=psutil.virtual_memory()
            return [TextContent(type="text", text=f"Total: {m.total//1024//1024}MB, Used: {m.used//1024//1024}MB, Free: {m.available//1024//1024}MB, Percent: {m.percent}%")]
        except ImportError:
            try:
                with open("/proc/meminfo") as f:
                    meminfo = f.read()
                return [TextContent(type="text", text=f"Memory info:\n{meminfo[:500]}")]
            except Exception as e2:
                return [TextContent(type="text", text=f"Memory: unavailable ({e2})")]
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
                # Ensure previous process is properly waited before retrying
                if proc.returncode is None:
                    await proc.wait()
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
                if proc.returncode is None:
                    await proc.wait()
            return [TextContent (type ="text",text ="Clipboard: no supported tool found (install xclip or wl-clipboard)")]
        except Exception as e :
            return [TextContent (type ="text",text =f"Error: {e }")]

    elif name =="get_current_time":
        now = datetime.now(timezone.utc)
        return [TextContent(type="text", text=now.isoformat())]

    elif name =="set_reminder":
        text =arguments .get ("text","")
        delay =int (arguments .get ("delay_seconds",60 ))

        async def _fire ():
            try:
                await asyncio .sleep (delay )
                logger.warning(f"REMINDER: {text}")
            except asyncio.CancelledError:
                pass
            finally:
                _reminder_tasks.pop(id(_fire), None)

        task = asyncio.create_task(_fire())
        _reminder_tasks[id(_fire)] = task
        return [TextContent (type ="text",text =f"Reminder set: \"{text }\" in {delay }s")]

    raise ValueError (f"Unknown tool: {name }")


if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    async def run ():
        try:
            async with stdio_server ()as (read_stream ,write_stream ):
                await app .run (read_stream ,write_stream ,app .create_initialization_options ())
        finally:
            # Cancel all pending reminders on shutdown
            for task in _reminder_tasks.values():
                task.cancel()
            if _reminder_tasks:
                await asyncio.gather(*_reminder_tasks.values(), return_exceptions=True)
            _reminder_tasks.clear()
    asyncio .run (run ())
