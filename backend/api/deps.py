"""
Shared component injection for API routes and WebSocket handler.
"""
import logging 

from backend .config .settings import Settings 
from backend .core .llm import LLMRouter 
from backend .core .memory import Memory 
from backend .core .context_builder import ContextBuilder 
from backend .core .context_manager import ContextManager 
from backend .core .vault import VaultManager 
from backend .core .agent import Agent 
from backend .core .relationship import Relationship 
from backend .mcp .client import MCPClient 
from backend .skills .loader import SkillLoader 
from backend .voice .tts import TTS 

logger =logging .getLogger (__name__ )

_shared ={
"settings":None ,
"llm":None ,
"memory":None ,
"context_builder":None ,
"context_manager":None ,
"vault":None ,
"mcp":None ,
"tts":None ,
"agent":None ,
"relationship":None ,
}


def _sync_emotion_tags ():
    """Sync TTS engine's supported emotions to the agent."""
    if _shared ["agent"]and _shared ["tts"]:
        supported =_shared ["tts"].get_supported_emotions ()
        _shared ["agent"].update_emotion_tags (supported if supported else _shared ["agent"]._emotion_tags )


def get_shared ():
    if _shared ["settings"]is None :
        _shared ["settings"]=Settings ()
    if _shared ["llm"]is None :
        _shared ["llm"]=LLMRouter (settings =_shared ["settings"])
    if _shared ["memory"]is None :
        _shared ["memory"]=Memory (llm_router =_shared ["llm"],settings =_shared ["settings"])
    if _shared ["context_builder"]is None :
        _shared ["context_builder"]=ContextBuilder (settings =_shared ["settings"])
    if _shared ["context_manager"]is None :
        _shared ["context_manager"]=ContextManager (settings =_shared ["settings"])
    if _shared ["vault"]is None :
        vault_path =_shared ["settings"].get ("vault.path","")
        _shared ["vault"]=VaultManager (vault_path )
    if _shared ["mcp"]is None :
        _shared ["mcp"]=MCPClient ()
        skill_loader =SkillLoader ()
        _shared ["mcp"].register_skill_loader (skill_loader )
    if _shared ["tts"]is None :
        engine =_shared ["settings"].get ("voice.engine","edge-tts")
        _shared ["tts"]=TTS (engine =engine )
        elevenlabs_key =_shared ["settings"].get ("voice.elevenlabs.api_key","")
        if elevenlabs_key :
            elevenlabs_model =_shared ["settings"].get ("voice.elevenlabs.model","eleven_multilingual_v2")
            _shared ["tts"].configure_elevenlabs (elevenlabs_key ,elevenlabs_model )
    if _shared ["relationship"]is None :
        _shared ["relationship"]=Relationship ()
    if _shared ["agent"]is None :
        _shared ["agent"]=Agent (
        mcp_client =_shared ["mcp"],
        llm =_shared ["llm"],
        memory =_shared ["memory"],
        context_builder =_shared ["context_builder"],
        settings =_shared ["settings"]
        )
        _sync_emotion_tags ()
    return _shared 


def settings ():return get_shared ()["settings"]
def llm ():return get_shared ()["llm"]
def memory ():return get_shared ()["memory"]
def context_builder ():return get_shared ()["context_builder"]
def context_manager ():return get_shared ()["context_manager"]
def vault ():return get_shared ()["vault"]
def mcp ():return get_shared ()["mcp"]
def tts ():return get_shared ()["tts"]
def agent ():return get_shared ()["agent"]
def relationship ():return get_shared ()["relationship"]
