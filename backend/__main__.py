"""
Amalgam entry point.
Start the web server (default), CLI mode, or gRPC server.

Usage:
  python -m backend              # Web server
  python -m backend --cli         # In-process interactive CLI
  python -m backend --cli --grpc  # CLI via remote gRPC server
  python -m backend --grpc        # gRPC server only
"""
import uvicorn 
import os 
import sys 
import argparse 
import logging 

sys .path .insert (0 ,os .path .dirname (os .path .dirname (os .path .abspath (__file__ ))))

logging .basicConfig (level =logging .WARNING ,format ='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger =logging .getLogger (__name__ )


def _kill_port (port ):
    """Kill any process listening on the given port."""
    import subprocess 
    try :
        result =subprocess .run (
        ["lsof","-ti",f":{port }"],
        capture_output =True ,text =True 
        )
        pids =result .stdout .strip ().split ('\n')
        pids =[p for p in pids if p ]
        if pids :
            for pid in pids :
                logger .debug (f"Killing existing process {pid } on port {port }")
                subprocess .run (["kill","-9",pid ],capture_output =True )
    except FileNotFoundError :
        try :
            subprocess .run (["fuser","-k",f"{port }/tcp"],capture_output =True )
        except FileNotFoundError :
            pass 


def main ():
    parser =argparse .ArgumentParser (description ="Amalgam")
    parser .add_argument ("--cli",action ="store_true",help ="Run in CLI mode (instead of web server)")
    parser .add_argument ("--grpc",action ="store_true",help ="Run gRPC server (or connect via CLI)")
    parser .add_argument ("--grpc-host",default ="0.0.0.0",help ="gRPC bind host")
    parser .add_argument ("--grpc-port",type =int ,default =50051 ,help ="gRPC bind port")
    args ,_ =parser .parse_known_args ()

    if args .grpc and not args .cli :

        logging .getLogger ().setLevel (logging .INFO )
        import asyncio 
        from backend .grpc .server import serve_grpc 
        asyncio .run (serve_grpc (args .grpc_host ,args .grpc_port ))
    elif args .cli :

        from backend .cli import main as cli_main 
        cli_main ()
    else :

        port =int (os .environ .get ("AMALGAM_PORT","8000"))
        host =os .environ .get ("AMALGAM_HOST","0.0.0.0")
        _kill_port (port )
        logger .debug ("Starting Amalgam...")
        logger .debug (f"Chat UI: http://localhost:{port }")
        logger .debug ("Avatar: Three.js VRM (browser-rendered)")
        uvicorn .run (
        "backend.app:app",
        host =host ,
        port =port ,
        log_level ="warning",
        reload =False 
        )


if __name__ =="__main__":
    main ()
