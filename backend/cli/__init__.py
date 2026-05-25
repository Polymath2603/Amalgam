"""
CLI mode — interactive terminal interface for the agent.
Runs in-process (direct) or connects to a remote gRPC server.
"""
import asyncio 
import argparse 
import sys 
import logging 

logger =logging .getLogger (__name__ )


def _make_console ():
    from rich .console import Console 
    return Console ()


def _show_banner (console ,session_id ,provider ,model ):
    from rich .panel import Panel 
    from rich .table import Table 
    from rich import box 
    grid =Table .grid (padding =1 )
    grid .add_column (style ="cyan")
    grid .add_column ()
    grid .add_row ("Session",f"[bold]{session_id [:16 ]}...[/bold]")
    grid .add_row ("Provider",provider )
    grid .add_row ("Model",model )
    console .print (Panel (grid ,title ="[bold yellow]Amalgam[/bold yellow]",border_style ="yellow"))
    console .print ("[dim]Type /exit to quit, /new for new session, /help for commands[/dim]\n")


async def run_cli_direct ():
    """Run the agent directly in-process (no gRPC needed)."""
    from k_core .deps import get_shared 

    shared =get_shared ()
    agent =shared ["agent"]
    memory =shared ["memory"]
    settings =shared ["settings"]

    session_id =memory .start_session ()
    active =settings .get ("provider.active","?")
    model =settings .get (f"provider.{active }.model","?")
    con =_make_console ()
    _show_banner (con ,session_id ,active ,model )

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
        elif text =="/new":
            session_id =memory .start_session ()
            con .print (f"[green]New session:[/green] {session_id [:16 ]}...")
            continue 
        elif text =="/help":
            from rich .table import Table 
            from rich import box 
            tbl =Table (box =box .SIMPLE ,show_header =False )
            tbl .add_column ("Command",style ="cyan")
            tbl .add_column ("Description")
            for row in [
            ("/exit","Quit the CLI"),
            ("/clear","Clear conversation history"),
            ("/new","Start a new session"),
            ("/session","Show current session ID"),
            ("/status","Show provider, model, session info"),
            ("/compact","Force memory compaction"),
            ("/provider <name>","Switch AI provider"),
            ("/model <name>","Switch model for current provider"),
            ("/help","Show this help"),
            ]:
                tbl .add_row (*row )
            con .print (tbl )
            continue 
        elif text =="/clear":
            await memory .clear ()
            memory .start_session ()
            con .print ("[green]Memory cleared.[/green]")
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
        elif text .startswith ("/provider"):
            parts =text .split ()
            if len (parts )>1 :
                settings .set ("provider.active",parts [1 ])
                con .print (f"[green]Provider set to:[/green] {parts [1 ]}")
            else :
                con .print (f"Current provider: {settings .get ('provider.active')}")
            continue 
        elif text .startswith ("/model"):
            provider =settings .get ("provider.active","gemini")
            parts =text .split (maxsplit =1 )
            if len (parts )>1 :
                settings .set (f"provider.{provider }.model",parts [1 ])
                con .print (f"[green]Model set to:[/green] {parts [1 ]}")
            else :
                con .print (f"Current model: {settings .get (f'provider.{provider }.model','?')}")
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
                    con .print (Panel (f"[red]{tag_val }[/red]",title ="[bold red]Error[/bold red]",border_style ="red"))
            else :
                con .print (chunk ,end ="")
        con .print ()


async def run_cli_grpc (host :str ="localhost",port :int =50051 ):
    """Connect to a remote gRPC agent server."""
    import grpc 
    from backend .grpc import agent_pb2 ,agent_pb2_grpc 

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

            async def send_messages ():
                yield agent_pb2 .ChatRequest (text =text )

            from rich .panel import Panel 
            async for response in stub .Chat (send_messages ()):
                which =response .WhichOneof ("payload")
                if which =="text_chunk":
                    con .print (response .text_chunk ,end ="")
                elif which =="thinking":
                    con .print (f"[dim]\\[thinking] {response .thinking }[/dim]")
                elif which =="tool_call":
                    con .print (Panel (f"[cyan]{response .tool_call .name }[/cyan]",title ="Tool",border_style ="cyan"))
                elif which =="permission_request":
                    pr =response .permission_request 
                    con .print (Panel (f"[yellow]{pr .cmd }[/yellow]",title ="Permission Needed",border_style ="yellow"))
                    from rich .prompt import Prompt 
                    action =Prompt .ask ("  Options",choices =list (pr .options ),default ="deny")
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
    args ,_ =parser .parse_known_args ()

    logging .basicConfig (level =logging .WARNING )

    if args .grpc :
        asyncio .run (run_cli_grpc (args .host ,args .port ))
    else :
        asyncio .run (run_cli_direct ())


if __name__ =="__main__":
    main ()
