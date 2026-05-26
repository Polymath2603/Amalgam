"""
Amalgam entry point.
Launches the backend server and a chosen frontend.

Usage:
  python main.py help               # Print this help
  python main.py webui              # Launch web UI
  python main.py cli                # Launch interactive CLI
  python main.py --grpc             # gRPC server only
  python main.py cli --grpc         # CLI via remote gRPC
"""
import os 
import sys 
import argparse 
import logging 

sys .path .insert (0 ,os .path .dirname (os .path .abspath (__file__ )))
logging .basicConfig (level =logging .WARNING ,format ='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger =logging .getLogger (__name__ )


def _kill_port (port ):
    import subprocess 
    try :
        result =subprocess .run (["lsof","-ti",f":{port }"],capture_output =True ,text =True )
        pids =[p for p in result .stdout .strip ().split ('\n')if p ]
        if pids :
            for pid in pids :
                subprocess .run (["kill","-9",pid ],capture_output =True )
    except FileNotFoundError :
        try :
            subprocess .run (["fuser","-k",f"{port }/tcp"],capture_output =True )
        except FileNotFoundError :
            pass 


def _print_help ():
    print (__doc__ .strip ())
    print ()
    print ("Available frontends: default, webui, cli")
    print ("  default  - Launch web UI (default)")
    print ("  webui    - Launch web UI")
    print ("  cli      - Launch interactive CLI")
    print ()
    print ("Options:")
    print ("  --grpc         Run gRPC server (or connect via CLI)")
    print ("  --grpc-host    gRPC bind host (default: 0.0.0.0)")
    print ("  --grpc-port    gRPC bind port (default: 50051)")


def main ():
    parser =argparse .ArgumentParser (description ="Amalgam")
    parser .add_argument ("frontend",nargs ="?",
    choices =["help","webui","cli"],
    help ="Frontend to launch")
    parser .add_argument ("--grpc",action ="store_true",help ="Run gRPC server (or connect via CLI)")
    parser .add_argument ("--grpc-host",default ="0.0.0.0",help ="gRPC bind host")
    parser .add_argument ("--grpc-port",type =int ,default =50051 ,help ="gRPC bind port")
    args =parser .parse_args ()

    if args .frontend is None or args .frontend =="help":
        _print_help ()
        return 

    if args .grpc and args .frontend !="cli":
        import asyncio 
        from backend .grpc .server import serve_grpc 
        asyncio .run (serve_grpc (args .grpc_host ,args .grpc_port ))
    elif args .frontend =="cli":
        from frontend .cli import main as cli_main 
        cli_main ()
    else :
        port =int (os .environ .get ("AMALGAM_PORT","8000"))
        host =os .environ .get ("AMALGAM_HOST","0.0.0.0")
        _kill_port (port )
        import uvicorn 
        logger .info ("Starting Amalgam web UI...")
        logger .info (f"Chat UI: http://localhost:{port }")
        uvicorn .run (
        "backend.app:app",
        host =host ,
        port =port ,
        log_level ="warning",
        reload =False 
        )


if __name__ =="__main__":
    main ()
