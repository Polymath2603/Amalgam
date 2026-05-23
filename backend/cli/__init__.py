"""
CLI mode — interactive terminal interface for the agent.
Runs in-process (direct) or connects to a remote gRPC server.
"""
import asyncio 
import argparse 
import sys 
import logging 

logger =logging .getLogger (__name__ )


async def run_cli_direct ():
    """Run the agent directly in-process (no gRPC needed)."""
    from backend .api .deps import get_shared 

    shared =get_shared ()
    agent =shared ["agent"]
    memory =shared ["memory"]
    settings =shared ["settings"]

    session_id =memory .start_session ()
    print (f"Session: {session_id }")
    print ("Type /exit to quit, /new for new session, /help for commands")
    print ()

    while True :
        try :
            text =input ("> ").strip ()
        except (EOFError ,KeyboardInterrupt ):
            print ()
            break 

        if not text :
            continue 

        if text =="/exit":
            break 
        elif text =="/new":
            session_id =memory .start_session ()
            print (f"New session: {session_id }")
            continue 
        elif text =="/help":
            print ("Commands: /exit /new /session /provider /model /help")
            continue 
        elif text =="/session":
            print (f"Current session: {memory .get_current_session ()}")
            continue 
        elif text .startswith ("/provider"):
            parts =text .split ()
            if len (parts )>1 :
                settings .set ("provider.active",parts [1 ])
                print (f"Provider set to: {parts [1 ]}")
            else :
                print (f"Current provider: {settings .get ('provider.active')}")
            continue 
        elif text .startswith ("/model"):
            provider =settings .get ("provider.active","gemini")
            parts =text .split (maxsplit =1 )
            if len (parts )>1 :
                settings .set (f"provider.{provider }.model",parts [1 ])
                print (f"Model set to: {parts [1 ]}")
            else :
                print (f"Current model: {settings .get (f'provider.{provider }.model','?')}")
            continue 

        async for chunk in agent .handle_user_input (text ):
            if isinstance (chunk ,tuple ):
                tag_type ,tag_val =chunk 
                if tag_type =="__thinking__":
                    print (f"\033[90m[thinking] {tag_val }\033[0m")
                elif tag_type =="__emotion__":
                    pass 
                elif tag_type =="__expression__":
                    pass 
                elif tag_type =="__roleplay__":
                    print (f"\033[93m* {tag_val } *\033[0m")
                elif tag_type =="__tool__":
                    print (f"\033[94m[Tool] {tag_val }\033[0m")
                elif tag_type =="__permission__":
                    print (f"\033[91m[Permission needed] {tag_val }\033[0m")
                    print ("  Options: once / prefix / exact / deny")
                    action =input ("  > ").strip ().lower ()

                    print (f"  {action }")
                elif tag_type =="__error__":
                    print (f"\033[91m[Error] {tag_val }\033[0m")
            else :
                print (chunk ,end ="",flush =True )
        print ()


async def run_cli_grpc (host :str ="localhost",port :int =50051 ):
    """Connect to a remote gRPC agent server."""
    import grpc 
    from backend .grpc import agent_pb2 ,agent_pb2_grpc 

    async with grpc .aio .insecure_channel (f"{host }:{port }")as channel :
        stub =agent_pb2_grpc .AgentServiceStub (channel )

        print (f"Connected to gRPC server at {host }:{port }")
        print ("Type /exit to quit")
        print ()

        while True :
            try :
                text =input ("> ").strip ()
            except (EOFError ,KeyboardInterrupt ):
                print ()
                break 

            if not text :
                continue 
            if text =="/exit":
                break 

            async def send_messages ():
                yield agent_pb2 .ChatRequest (text =text )

            async for response in stub .Chat (send_messages ()):
                which =response .WhichOneof ("payload")
                if which =="text_chunk":
                    print (response .text_chunk ,end ="",flush =True )
                elif which =="thinking":
                    print (f"\033[90m[thinking] {response .thinking }\033[0m")
                elif which =="tool_call":
                    print (f"\033[94m[Tool] {response .tool_call .name }\033[0m")
                elif which =="permission_request":
                    pr =response .permission_request 
                    print (f"\033[91m[Permission needed] {pr .cmd }\033[0m")
                    print (f"  Options: {', '.join (pr .options )}")
                    action =input ("  > ").strip ().lower ()
                elif which =="error":
                    print (f"\033[91m[Error] {response .error }\033[0m")
                elif which =="done":
                    print ()
                    break 


def main ():
    parser =argparse .ArgumentParser (description ="Full-functioning CLI mode")
    parser .add_argument ("--grpc",action ="store_true",help ="Connect via gRPC")
    parser .add_argument ("--host",default ="localhost",help ="gRPC host")
    parser .add_argument ("--port",type =int ,default =50051 ,help ="gRPC port")
    args =parser .parse_args ()

    logging .basicConfig (level =logging .WARNING )

    if args .grpc :
        asyncio .run (run_cli_grpc (args .host ,args .port ))
    else :
        asyncio .run (run_cli_direct ())


if __name__ =="__main__":
    main ()
