"""
Amalgam entry point.
Starts the FastAPI backend (serves web UI + WebSocket + REST API).
Avatar rendering is done in the browser via Three.js + VRM.
"""
import uvicorn 
import os 
import sys 
import logging 

sys .path .insert (0 ,os .path .dirname (os .path .dirname (os .path .abspath (__file__ ))))

logging .basicConfig (level =logging .INFO ,format ='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

for _noise in ("httpx","huggingface_hub","urllib3","httpcore","filelock","transformers",
"jieba","melo","openvoice","wavmark","torch","numba","librosa"):
    logging .getLogger (_noise ).setLevel (logging .WARNING )
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
                logger .info (f"Killing existing process {pid } on port {port }")
                subprocess .run (["kill","-9",pid ],capture_output =True )
    except FileNotFoundError :

        try :
            subprocess .run (["fuser","-k",f"{port }/tcp"],capture_output =True )
        except FileNotFoundError :
            pass 


def main ():
    _kill_port (8000 )
    logger .info ("Starting Amalgam...")
    logger .info ("Chat UI: http://localhost:8000")
    logger .info ("Avatar: Three.js VRM (browser-rendered)")
    uvicorn .run (
    "backend.api.server:app",
    host ="0.0.0.0",
    port =8000 ,
    log_level ="info",
    reload =False 
    )


if __name__ =="__main__":
    main ()
