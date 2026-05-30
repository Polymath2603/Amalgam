"""
Shared component injection — used by CLI, gRPC, and WebUI.
Not part of the `api` package to avoid cross-boundary imports.
"""
import logging 

from backend .core .config .settings import Settings 
from backend .core .llm import LLMRouter 
from backend .core .memory import Memory 
from backend .core .context_builder import ContextBuilder 
from backend .core .context_manager import ContextManager 
from backend .core .vault import VaultManager 
from backend .core .paths import EMBEDDINGS_DIR 
from backend .core .agent import Agent 
from backend .core .relationship import Relationship 
from backend .core .mcp .client import MCPClient 
from backend .core .voice .tts import TTS 
from backend .voice .wakeword import WakeWordRouter 

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
"wakeword":None ,
}


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
        _shared ["vault"]=VaultManager (vault_path ,embeddings_path =str (EMBEDDINGS_DIR ))
    if _shared ["mcp"]is None :
        _shared ["mcp"]=MCPClient ()
    if _shared ["tts"]is None :
        engine =_shared ["settings"].get ("voice.engine","edge-tts")
        _shared ["tts"]=TTS (engine =engine )
        elevenlabs_key =_shared ["settings"].get ("voice.elevenlabs.api_key","")
        if elevenlabs_key :
            elevenlabs_model =_shared ["settings"].get ("voice.elevenlabs.model","eleven_multilingual_v2")
            _shared ["tts"].configure_elevenlabs (elevenlabs_key ,elevenlabs_model )

        azure_key =_shared ["settings"].get ("voice.azure.api_key","")
        if azure_key :
            azure_region =_shared ["settings"].get ("voice.azure.region","eastus")
            _shared ["tts"].configure_azure (azure_key ,azure_region )

        dashscope_key =_shared ["settings"].get ("voice.dashscope.api_key","")
        if dashscope_key :
            dashscope_model =_shared ["settings"].get ("voice.dashscope.model","cosyvoice-v1")
            _shared ["tts"].configure_dashscope (dashscope_key ,dashscope_model )

        volcengine_app_id =_shared ["settings"].get ("voice.volcengine.app_id","")
        volcengine_token =_shared ["settings"].get ("voice.volcengine.access_token","")
        if volcengine_app_id and volcengine_token :
            volcengine_cluster =_shared ["settings"].get ("voice.volcengine.cluster","volcano_tts")
            _shared ["tts"].configure_volcengine (volcengine_app_id ,volcengine_token ,volcengine_cluster )

        deepgram_key =_shared ["settings"].get ("voice.deepgram.api_key","")
        if deepgram_key :
            deepgram_model =_shared ["settings"].get ("voice.deepgram.model","aura-2")
            _shared ["tts"].configure_deepgram (deepgram_key ,deepgram_model )
    if _shared ["relationship"]is None :
        _shared ["relationship"]=Relationship ()
    if _shared ["wakeword"]is None :
        ww_engine =_shared ["settings"].get ("wake_word.engine","openwakeword")
        _shared ["wakeword"]=WakeWordRouter (engine =ww_engine )
    if _shared ["agent"]is None :
        _shared ["agent"]=Agent (
        mcp_client =_shared ["mcp"],
        llm =_shared ["llm"],
        memory =_shared ["memory"],
        context_builder =_shared ["context_builder"],
        settings =_shared ["settings"]
        )
        _shared ["mcp"].register_agent (_shared ["agent"])
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
def wakeword ():return get_shared ()["wakeword"]
