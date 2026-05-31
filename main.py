"""
Amalgam launcher.

Usage:
  python main.py help               
  python main.py desktop            
  python main.py webui              
  python main.py cli                
  python main.py --grpc             
  python main.py cli --grpc         
"""
import os 
import sys 
import argparse 

os .environ ["HF_HUB_DISABLE_SYMLINKS_WARNING"]="1"
os .environ ["HF_TOKEN"]=""

sys .path .insert (0 ,os .path .dirname (os .path .abspath (__file__ )))

TAURI_DIR =os .path .join (os .path .dirname (os .path .abspath (__file__ )),"desktop","tauri")

LOG_LEVEL_MAP ={0 :"ERROR",1 :"WARNING",2 :"INFO",3 :"DEBUG"}


def _verbosity_to_level (v :int )->str :
    return LOG_LEVEL_MAP .get (v ,"DEBUG")


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
    print ("Usage: python main.py [command] [options]")
    print ()
    print ("Commands:")
    print ("  webui    - Launch web UI (default)")
    print ("  cli      - Launch interactive CLI")
    print ("  desktop  - Build and launch Tauri desktop app")
    print ()
    print ("Options:")
    print ("  --grpc         Run gRPC server (or connect via CLI)")
    print ("  --grpc-host    gRPC bind host (default: 0.0.0.0)")
    print ("  --grpc-port    gRPC bind port (default: 50051)")
    print ("  -v             Verbosity: -v WARNING, -vv INFO, -vvv DEBUG (default: ERROR)")
    print ("  --log-level    Log level: ERROR|WARNING|INFO|DEBUG (overrides -v)")
    print ("  --log-format   Output format: console (default) or json")


def _launch_desktop (args =None ):
    import subprocess 
    if not os .path .isdir (TAURI_DIR ):
        print (f"Error: Tauri directory not found at {TAURI_DIR }")
        sys .exit (1 )

    print ("Starting backend server...")
    backend_args =[sys .executable ,__file__ ,"webui"]
    if args :
        if args .log_level :
            backend_args .extend (["--log-level",args .log_level ])
        elif args .verbose >0 :
            v ="-"+"v"*args .verbose 
            backend_args .append (v )
    server =subprocess .Popen (
    backend_args ,
    stdout =subprocess .DEVNULL ,stderr =subprocess .DEVNULL ,
    )

    import time ,urllib .request 
    print ("Waiting for backend...",end ="",flush =True )
    for _ in range (30 ):
        try :
            with urllib .request .urlopen ("http://localhost:8000/",timeout =1 )as r :
                if r .status ==200 :
                    break 
        except Exception :
            pass 
        print (".",end ="",flush =True )
        time .sleep (1 )
    else :
        print ("\nBackend failed to start")
        server .terminate ()
        return 
    print (" ready")

    print ("Launching desktop app...")
    print ("[if CSS looks wrong, run: cargo build in desktop/tauri/ to pick up changes]")
    env ={**os .environ ,"AMALGAM_SKIP_BACKEND":"1"}
    try :
        subprocess .run (["cargo","run"],cwd =TAURI_DIR ,env =env )
    except KeyboardInterrupt :
        print ("\nShutting down...")
    finally :
        server .terminate ()
        server .wait (timeout =5 )
        _kill_port (8000 )
        print ("Shut down.")


def main ():
    parser =argparse .ArgumentParser (description ="Amalgam")
    parser .add_argument ("frontend",nargs ="?",choices =["help","webui","cli","desktop","telegram"],
    help ="Frontend to launch (desktop is recommended)")
    parser .add_argument ("--grpc",action ="store_true",help ="Run gRPC server (or connect via CLI)")
    parser .add_argument ("--grpc-host",default ="0.0.0.0",help ="gRPC bind host")
    parser .add_argument ("--grpc-port",type =int ,default =50051 ,help ="gRPC bind port")
    parser .add_argument ("-v","--verbose",action ="count",default =0 ,
    help ="Verbosity: -v WARNING, -vv INFO, -vvv DEBUG (default: ERROR)")
    parser .add_argument ("--log-level",default =None ,choices =["DEBUG","INFO","WARNING","ERROR"],
    help ="Log level (overrides -v)")
    parser .add_argument ("--log-format",default =None ,choices =["console","json"],
    help ="Log output format")
    args =parser .parse_args ()

    from backend .core .log_config import configure_logging 
    log_level =args .log_level or _verbosity_to_level (args .verbose )
    logger =configure_logging (level =log_level ,log_format =args .log_format )

    if args .grpc and args .frontend !="cli":
        import asyncio 
        from backend .grpc .server import serve_grpc 
        asyncio .run (serve_grpc (args .grpc_host ,args .grpc_port ))
        return 

    if args .frontend is None or args .frontend =="help":
        _print_help ()
        return 

    if args .frontend =="desktop":
        _launch_desktop (args )
    elif args .frontend =="telegram":
        import asyncio 
        from backend .api .telegram import run_telegram 
        asyncio .run (run_telegram ())
    elif args .frontend =="cli":
        from cli import main as cli_main 
        cli_main ()
    else :
        port =int (os .environ .get ("AMALGAM_PORT","8000"))
        host =os .environ .get ("AMALGAM_HOST","0.0.0.0")
        _kill_port (port )
        import uvicorn 
        logger .info ("Starting Amalgam web UI...")
        logger .info (f"Chat UI: http://localhost:{port }")
        uvicorn_log =log_level .lower ()if log_level !="ERROR"else "error"
        uvicorn .run (
        "backend.app:app",
        host =host ,
        port =port ,
        log_level =uvicorn_log ,
        reload =False 
        )


if __name__ =="__main__":
    main ()
