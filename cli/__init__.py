"""
CLI mode — interactive terminal interface for the agent.
Runs in-process (direct) or connects to a remote gRPC server.
"""
import asyncio 
import argparse 
import logging 
import os 
import sys 

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts import clear

os .environ ["HF_HUB_DISABLE_SYMLINKS_WARNING"]="1"
os .environ ["HF_TOKEN"]=""

_COMMANDS =[
"/exit","/clear","/new","/session","/status",
"/compact","/provider","/model","/companion","/help","/rename",
]

_HISTFILE =os .path .join (os .path .expanduser ("~"),".amalgam_history")


def _make_console ():
    from rich .console import Console 
    return Console ()


def _show_banner (console ,session_id ,provider ,model ,title=None):
    from rich .panel import Panel 
    from rich .table import Table 
    from rich import box 
    grid =Table .grid (padding =1 )
    grid .add_column (style ="cyan")
    grid .add_column ()
    grid .add_row ("Session",f"[bold]{title or session_id[:16]}...[/bold]")
    grid .add_row ("Provider",provider )
    grid .add_row ("Model",model )
    console .print (Panel (grid ,title ="[bold yellow]Amalgam[/bold yellow]",border_style ="yellow"))
    console .print ("[dim]Type /exit to quit, /new for new session, /help for commands[/dim]\n")


def _suppress_logs():
    """Silence common library logs for CLI mode."""
    loggers = [
        "huggingface_hub", "huggingface_hub.utils._http", "urllib3", "httpx",
        "httpcore", "chromadb", "asyncio", "mcp.os.posix.utilities",
        "backend.core.llm.litellm_provider", "backend.core.memory.manager",
        "litellm", "aiosqlite", "vaderSentiment", "faster_whisper", "edge-tts"
    ]
    for name in loggers:
        logging.getLogger(name).setLevel(logging.CRITICAL)
    
    # Also set root logger to CRITICAL to be safe
    logging.getLogger().setLevel(logging.CRITICAL)


def _extract_error_message(error_str: str) -> str:
    """Try to extract 'message' from a potential JSON error string."""
    import json
    try:
        # Regex to find JSON-like content
        import re
        match = re.search(r'\{.*\}', error_str)
        if match:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and "error" in data and isinstance(data["error"], dict):
                return data["error"].get("message", error_str)
            return data.get("message", error_str)
    except:
        pass
    return error_str


async def run_cli_direct ():
    """Run the agent directly in-process (no gRPC needed)."""
    _suppress_logs()
    
    from backend .core .startup import init_application ,shutdown_application 
    await init_application ()

    from backend .core .deps import get_shared 

    shared =get_shared ()
    agent =shared ["agent"]
    memory =shared ["memory"]
    settings =shared ["settings"]
    llm =shared ["llm"]
    _voice_active =[False ]

    con = _make_console()

    # Initial banner
    sid = memory.get_current_session()
    data = await memory._read(sid)
    title = data.get("title") if data else None
    active = settings.get("provider.active", "?")
    model = settings.get(f"provider.{active}.model", "?")
    clear()
    _show_banner(con, sid, active, model, title=title)

    completer = WordCompleter(_COMMANDS)
    prompt_session = PromptSession(history=None, completer=completer)

    try :
        while True :
            try :
                text = await prompt_session.prompt_async("> ")
                text = text.strip()
            except EOFError :
                con .print ()
                break 
            except KeyboardInterrupt :
                con .print ()
                continue 

            if not text :
                continue 

            if text =="/exit":
                break 
            elif text =="/new":
                session_id =memory .start_session ()
                active =settings .get ("provider.active","?")
                model =settings .get (f"provider.{active }.model","?")
                data = await memory._read(session_id)
                title = data.get("title") if data else None
                clear()
                _show_banner (con ,session_id ,active ,model, title=title )
                continue 
            elif text =="/help":
                from rich .table import Table 
                from rich import box 
                tbl =Table (box =box .SIMPLE ,show_header =False )
                tbl .add_column ("Command",style ="cyan")
                tbl .add_column ("Description")
                for row in [
                ("/exit","Quit the CLI"),
                ("/clear","Clear terminal and reprint banner"),
                ("/new","Start a new session and clear screen"),
                ("/session","Show current session ID"),
                 ("/status","Show provider, model, session info"),
                 ("/compact","Force memory compaction"),
                 ("/provider <name>","Switch AI provider"),
                 ("/model <name>","Switch model for current provider"),
                 ("/rename <title>","Rename the current session"),
                 ("/companion","Toggle companion mode (voice + avatar)"),
                ]:
                    tbl .add_row (*row )
                con .print (tbl )
                continue 
            elif text =="/companion":
                _voice_active [0 ]=not _voice_active [0 ]
                if _voice_active [0 ]:
                    settings .set ("voice.input_enabled",True )
                    settings .set ("voice.output_enabled",True )
                    con .print ("[green]Companion mode ON[/green]")
                else :
                    settings .set ("voice.input_enabled",False )
                    settings .set ("voice.output_enabled",False )
                    con .print ("[red]Companion mode OFF[/red]")
                continue 

            elif text =="/clear":
                clear()
                active =settings .get ("provider.active","?")
                model =settings .get (f"provider.{active }.model","?")
                sid = memory.get_current_session()
                data = await memory._read(sid)
                title = data.get("title") if data else None
                _show_banner (con ,sid, active ,model, title=title )
                continue 
            elif text =="/session":
                con .print (f"[cyan]Session:[/cyan] {memory .get_current_session ()}")
                continue 
            elif text =="/status":
                from rich .table import Table 
                from rich import box 
                active =settings .get ("provider.active","?")
                model =settings .get (f"provider.{active }.model","?")
                tbl =Table (box =box .SIMPLE ,show_header =False )
                tbl .add_column ("Key",style ="cyan")
                tbl .add_column ("Value")
                tbl .add_row ("Provider",active )
                tbl .add_row ("Model",model )
                tbl .add_row ("Session",memory .get_current_session ())
                con .print (tbl )
                continue 
            elif text =="/compact":
                with con .status ("[yellow]Compacting memory...[/yellow]"):
                    await memory .check_and_summarize ()
                con .print ("[green]Memory compacted.[/green]")
                continue 
            elif text .startswith ("/rename"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    sid = memory.get_current_session()
                    try:
                        new_title = await memory.rename_session(sid, parts[1])
                        con.print(f"[green]Session renamed to:[/green] {new_title}")
                        # Refresh banner
                        active = settings.get("provider.active", "?")
                        model = settings.get(f"provider.{active}.model", "?")
                        clear()
                        _show_banner(con, sid, active, model, title=new_title)
                    except ValueError as e:
                        con.print(f"[red]Error:[/red] {e}")
                continue

            elif text == "/resume":
                sid = memory.get_current_session()
                turns = memory.get_session_turns(sid, turns=5)
                con.print(f"[cyan]Resuming last 5 turns of {sid}:[/cyan]")
                for turn in turns:
                    con.print(f"[bold]{turn['role'].upper()}:[/bold] {turn['content']}")
                continue
            elif text .startswith ("/provider"):
                parts =text .split ()
                if len (parts )>1 :
                    settings .set ("provider.active",parts [1 ])
                    llm.reload_settings()
                    active = parts[1]
                    model = settings.get(f"provider.{active}.model", "?")
                    sid = memory.get_current_session()
                    data = await memory._read(sid)
                    title = data.get("title") if data else None
                    clear()
                    _show_banner (con ,sid, active ,model, title=title )
                else :
                    con .print (f"Current provider: {settings .get ('provider.active')}")
                continue 
            elif text .startswith ("/model"):
                provider =settings .get ("provider.active","gemini")
                parts =text .split (maxsplit =1 )
                if len (parts )>1 :
                    settings .set (f"provider.{provider }.model",parts [1 ])
                    llm.reload_settings()
                    model = parts[1]
                    sid = memory.get_current_session()
                    data = await memory._read(sid)
                    title = data.get("title") if data else None
                    clear()
                    _show_banner (con ,sid, provider ,model, title=title )
                else :
                    con .print (f"Current model: {settings .get (f'provider.{provider }.model','?')}")
                continue 

            if text .startswith ("/"):
                con .print (f"[red]Unknown command:[/red] {text }")
                continue 

            from rich .panel import Panel 
            async for chunk in agent .handle_user_input (text ):
                if isinstance (chunk ,tuple ):
                    tag_type ,tag_val =chunk 
                    if tag_type =="__thinking__":
                        con .print (f"[dim]\\[thinking] {tag_val }[/dim]")
                    elif tag_type =="__roleplay__":
                        con .print (f"[yellow]* {tag_val } *[/yellow]")
                    elif tag_type =="__tool__":
                        con .print (Panel (f"[cyan]{tag_val }[/cyan]",title ="[bold cyan]Tool[/bold cyan]",border_style ="cyan"))
                    elif tag_type =="__permission__":
                        from rich .prompt import Prompt 
                        con .print (Panel (f"[yellow]{tag_val }[/yellow]",title ="[bold yellow]Permission Needed[/bold yellow]",border_style ="yellow"))
                        action =Prompt .ask ("  Options",choices =["once","prefix","exact","deny"],default ="deny")
                        con .print (f"  {action }")
                    elif tag_type =="__error__":
                        msg = _extract_error_message(tag_val)
                        con .print (Panel (f"[red]{msg }[/red]",title ="[bold red]Error[/bold red]",border_style ="red"))

                else :
                    con .print (chunk ,end ="")
            con .print ()
    finally :
        import readline 
        try :
            readline .write_history_file (_HISTFILE )
        except Exception :
            pass 
        await shutdown_application ()


async def run_cli_grpc (host :str ="localhost",port :int =50051 ):
    """Connect to a remote gRPC agent server."""
    import grpc 
    from backend .grpc import agent_pb2 ,agent_pb2_grpc 
    from rich .panel import Panel 

    con =_make_console ()

    async with grpc .aio .insecure_channel (f"{host }:{port }")as channel :
        stub =agent_pb2_grpc .AgentServiceStub (channel )
        con .print (f"[green]Connected to gRPC server at[/green] {host }:{port }")
        con .print ("[dim]Type /exit to quit[/dim]\n")

        while True :
            try :
                text =con .input ("[bold cyan]>[/bold cyan] ").strip ()
            except (EOFError ,KeyboardInterrupt ):
                con .print ()
                break 

            if not text :
                continue 
            if text =="/exit":
                break 

            async def send ():
                yield agent_pb2 .ChatRequest (text =text )

            from rich .prompt import Prompt 
            async for response in stub .Chat (send ()):
                which =response .WhichOneof ("payload")
                if which =="text_chunk":
                    con .print (response .text_chunk ,end ="")
                elif which =="thinking":
                    con .print (f"[dim]\\[thinking] {response .thinking }[/dim]")
                elif which =="tool_call":
                    tc =response .tool_call 
                    con .print (Panel (f"[cyan]{tc .name }({tc .args_json })[/cyan]",title ="Tool",border_style ="cyan"))
                elif which =="permission_request":
                    pr =response .permission_request 
                    con .print (Panel (f"[yellow]{pr .cmd }[/yellow]",title ="Permission Needed",border_style ="yellow"))
                    Prompt .ask ("  Options",choices =list (pr .options ),default ="deny")
                elif which =="error":
                    con .print (Panel (f"[red]{response .error }[/red]",title ="Error",border_style ="red"))
                elif which =="done":
                    con .print ()
                    break 


def main ():
    parser =argparse .ArgumentParser (description ="Full-functioning CLI mode")
    parser .add_argument ("--grpc",action ="store_true",help ="Connect via gRPC")
    parser .add_argument ("--host",default ="localhost",help ="gRPC host")
    parser .add_argument ("--port",type =int ,default =50051 ,help ="gRPC port")
    parser .add_argument ("--log-level",default =None ,choices =["DEBUG","INFO","WARNING","ERROR"],
    help ="Override log level")
    parser .add_argument ("--log-format",default =None ,choices =["console","json"],
    help ="Log output format")
    args ,_ =parser .parse_known_args ()

    from backend .core .log_config import configure_logging 
    logger =configure_logging (level =args .log_level ,log_format =args .log_format )

    try :
        if args .grpc :
            asyncio .run (run_cli_grpc (args .host ,args .port ))
        else :
            asyncio .run (run_cli_direct ())
    except KeyboardInterrupt :
        pass 


if __name__ =="__main__":
    main ()
