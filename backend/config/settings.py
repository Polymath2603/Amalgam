"""
Persistent settings manager. Reads/writes user_data/settings.json.
All settings have defaults so the app always boots even if the file is missing.
"""
import json 
import os 
import yaml 
import logging 
from typing import Any ,Dict ,List 
from backend .paths import CHARACTERS_DIR ,SETTINGS_PATH ,PROJECT_ROOT ,VAULT_DIR 

logger =logging .getLogger (__name__ )

DEFAULTS ={
"provider":{
"active":"gemini",
"ollama":{
"base_url":"http://localhost:11434",
"model":""
},
"gemini":{
"api_key":"",
"model":"gemini-2.5-flash",
"base_url":"https://generativelanguage.googleapis.com/v1beta"
},
"openrouter":{
"api_key":"",
"model":"meta-llama/llama-3.1-8b-instruct:free",
"base_url":"https://openrouter.ai/api/v1"
},
"zai":{
"api_key":"",
"model":"GLM-5.1",
"base_url":"https://api.z.ai/api/coding/paas/v4"
},
"siliconflow":{
"api_key":"",
"model":"Qwen/Qwen2.5-7B-Instruct",
"base_url":"https://api.siliconflow.cn/v1"
},
"groq":{
"api_key":"",
"model":"llama-3.3-70b-versatile",
"base_url":"https://api.groq.com/openai/v1"
},
"chatgpt":{
"api_key":"",
"model":"gpt-4o-mini",
"base_url":"https://api.openai.com/v1"
},
"claude":{
"api_key":"",
"model":"claude-sonnet-4-20250514",
"base_url":"https://api.anthropic.com/v1"
},
"llamacpp":{
"base_url":"http://localhost:8080",
"model":""
},
"koboldai":{
"base_url":"http://localhost:5001",
"model":""
}
},
"character":{
"active":"default",
"system_prompt":"",
"rules":""
},
"voice":{
"engine":"edge-tts",
"lipsync_enabled":True ,
"stt_engine":"browser",
"vad_mode":2 ,
"vad_frame_size":960 ,
"vad_energy_threshold":0.02 ,
"vad_silence_frames":33 ,
"faster_whisper":{
"model":"base"
},
"openai_whisper":{
"api_key":"",
"model":"whisper-1"
},
"openai_tts":{
"api_key":"",
"model":"tts-1",
"base_url":"https://api.openai.com/v1"
},
"alltalk":{
"url":"http://127.0.0.1:7851",
"language":"en",
"version":"v2",
"rvc_voice":"",
"rvc_pitch":"0"
},
"piper":{
"url":"http://127.0.0.1:5000"
},
"coqui_local":{
"url":"http://127.0.0.1:5002",
"speaker_id":""
},
"kokoro":{
"url":"http://127.0.0.1:8880"
},
"groq_whisper":{
"api_key":"",
"model":"whisper-large-v3",
"base_url":"https://api.groq.com/openai/v1"
},
"whispercpp":{
"url":"http://127.0.0.1:8080"
},
"tts_timeout":60.0 
},
"llm":{
"temperature":0.7 ,
"max_tokens":2048 ,
"timeout":120.0 ,
"context_token_limit":8192 
},
"memory":{
"retrieval_k":3 ,
"context_window":50 ,
"summarize_threshold":40 ,
"summarize_keep":15 ,
"embedding_backend":"provider",
"fact_extraction":True 
},
"avatar":{
"model_path":"",
"scale":1.0 
},
"vault":{
"path":str (VAULT_DIR )
},
"shell":{
"mode":"safe",
"allowed_prefixes":[
"echo","ls","cat","pwd","date",
"find","grep","head","tail","wc",
"mkdir","cp","mv","rm","touch",
"curl","wget",
"python3","python",
"pip","pip3",
"whoami","uname","notify-send",
"ps","top","htop",
"df","du","free",
"which","kill","pkill",
"xdotool","xclip","wl-paste"
]
},
"ui":{
"theme":"dark",
"font_size":14 ,
"voice_input":True ,
"voice_output":True ,
"thinking_enabled":True ,
},
"mcp":{
"servers":[
{
"name":"shell",
"command":"python3",
"args":[str (PROJECT_ROOT /"backend"/"mcp"/"servers"/"shell"/"server.py")],
"enabled":True ,
"env":{
"AMALGAM_SHELL_MODE":"safe",
"AMALGAM_SHELL_ALLOWED_COMMANDS":"echo,ls,cat,pwd,date,find,grep,head,tail,wc,mkdir,cp,mv,rm,touch,curl,wget,python3,python,pip,pip3,whoami,uname,notify-send,ps,top,htop,df,du,free,which,kill,pkill,xdotool,xclip,wl-paste,git status,git log,git diff"
}
},
{
"name":"screenshot",
"command":"python3",
"args":[str (PROJECT_ROOT /"backend"/"mcp"/"servers"/"screenshot"/"server.py")],
"enabled":True 
},
{
"name":"sequential-thinking",
"command":"npx",
"args":["-y","@modelcontextprotocol/server-sequential-thinking"],
"enabled":True 
},
{
"name":"puppeteer",
"command":"npx",
"args":["-y","@modelcontextprotocol/server-puppeteer"],
"enabled":True 
},
{
"name":"obsidian",
"command":"npx",
"args":["-y","obsidian-mcp",str (VAULT_DIR )],
"enabled":True 
},
{
"name":"system",
"command":"python3",
"args":[str (PROJECT_ROOT /"backend"/"mcp"/"servers"/"system"/"server.py")],
"enabled":True 
}
]
}
}



_DEFAULT_CHARACTER ={
"name":"Assistant",
"description":"A helpful AI assistant",
"voice":"en-US-AriaNeural",
"personality":"helpful_assistant",
"characteristics":"helpful, concise, friendly, intelligent",
"interaction_style":"direct, polite, engaging",
"vocabulary":["How can I help?","Let me look into that.","That's an interesting perspective."],
"system_prompt":"You are a helpful and intelligent AI assistant. You possess a wide range of knowledge and aim to be as helpful as possible while maintaining a friendly and professional demeanor. Be concise when appropriate, but don't hesitate to provide detailed explanations if needed. You are aware of your digital nature but strive to communicate with human-like warmth and empathy.",
"dialogue_examples":[
"User: Hello! Assistant: Hello there! [happy] How can I assist you today?",
"User: Can you help me with a problem? Assistant: Of course! [relaxed] Tell me all about it, and I'll do my best to help."
],
"quirks":[],
"memory_bias":[],
"forbidden":[],
"mood_baseline":0.6 ,
"mood_volatility":0.3 ,
}

def _load_single_character (char_dir :str )->Dict [str ,Dict ]|None :
    """Load a single character from its directory."""
    index_path =os .path .join (CHARACTERS_DIR ,char_dir ,"index.yaml")
    if not os .path .isfile (index_path ):
        return None 
    try :
        with open (index_path ,"r")as f :
            char_data =yaml .safe_load (f )or {}
        char_id =char_dir .lower ()

        for key ,val in _DEFAULT_CHARACTER .items ():
            if key not in char_data :
                char_data [key ]=val 

        icon_path =os .path .join (CHARACTERS_DIR ,char_dir ,"icon.png")
        model_path =os .path .join (CHARACTERS_DIR ,char_dir ,"model.vrm")
        char_data ["_dir"]=os .path .join (CHARACTERS_DIR ,char_dir )
        char_data ["icon_url"]=f"/characters/{char_id }/icon.png"if os .path .exists (icon_path )else "/icons/logo.png"
        char_data ["model_url"]=f"/characters/{char_id }/model.vrm"if os .path .exists (model_path )else ""

        if not char_data .get ("voice_ref"):
            voice_pth =os .path .join (CHARACTERS_DIR ,char_dir ,"voice.pth")
            voice_wav =os .path .join (CHARACTERS_DIR ,char_dir ,"voice.wav")
            if os .path .exists (voice_pth ):
                char_data ["voice_ref"]=voice_pth 
            elif os .path .exists (voice_wav ):
                char_data ["voice_ref"]=voice_wav 
        return {char_id :char_data }
    except Exception as e :
        logger .error (f"Failed to load character from {index_path }: {e }")
        return None 

def load_characters_from_yaml ()->Dict [str ,Dict ]:
    """Load all character definitions from characters/*/index.yaml."""
    characters ={}
    if not os .path .exists (CHARACTERS_DIR ):
        return characters 


    for char_dir in sorted (os .listdir (CHARACTERS_DIR )):
        if char_dir .lower ()=="default":
            result =_load_single_character (char_dir )
            if result :
                characters .update (result )
            break 

    for char_dir in sorted (os .listdir (CHARACTERS_DIR )):
        if char_dir .lower ()=="default":
            continue 
        result =_load_single_character (char_dir )
        if result :
            characters .update (result )


    if "default"not in characters :
        characters ["default"]={**_DEFAULT_CHARACTER ,"icon_url":"/icons/logo.png","model_url":"","_dir":""}

    return characters 


BUILTIN_VOICES =[
{"id":"en-US-AriaNeural","name":"Aria","gender":"Female","locale":"en-US"},
{"id":"en-US-JennyNeural","name":"Jenny","gender":"Female","locale":"en-US"},
{"id":"en-US-GuyNeural","name":"Guy","gender":"Male","locale":"en-US"},
{"id":"en-US-DavisNeural","name":"Davis","gender":"Male","locale":"en-US"},
{"id":"en-US-AndrewNeural","name":"Andrew","gender":"Male","locale":"en-US"},
{"id":"en-US-EmmaNeural","name":"Emma","gender":"Female","locale":"en-US"},
{"id":"en-US-BrianNeural","name":"Brian","gender":"Male","locale":"en-US"},
{"id":"en-US-AndrewMultilingualNeural","name":"Andrew Multilingual","gender":"Male","locale":"en-US"},
{"id":"en-US-EmmaMultilingualNeural","name":"Emma Multilingual","gender":"Female","locale":"en-US"},
{"id":"en-US-BrianMultilingualNeural","name":"Brian Multilingual","gender":"Male","locale":"en-US"},
{"id":"en-GB-SoniaNeural","name":"Sonia","gender":"Female","locale":"en-GB"},
{"id":"en-GB-RyanNeural","name":"Ryan","gender":"Male","locale":"en-GB"},
{"id":"ja-JP-NanamiNeural","name":"Nanami","gender":"Female","locale":"ja-JP"},
{"id":"ja-JP-KeitaNeural","name":"Keita","gender":"Male","locale":"ja-JP"},
{"id":"fr-FR-DeniseNeural","name":"Denise","gender":"Female","locale":"fr-FR"},
{"id":"de-DE-KatjaNeural","name":"Katja","gender":"Female","locale":"de-DE"},
{"id":"es-ES-ElviraNeural","name":"Elvira","gender":"Female","locale":"es-ES"},
{"id":"ar-SA-ZariyahNeural","name":"Zariyah","gender":"Female","locale":"ar-SA"},
]




class Settings :
    def __init__ (self ,path :str =SETTINGS_PATH ):
        self .path =path 
        self .data ={}
        self ._characters =load_characters_from_yaml ()
        self .load ()

    def load (self ):
        if os .path .exists (self .path ):
            try :
                with open (self .path ,"r")as f :
                    self .data =json .load (f )
                logger .debug (f"Settings loaded from {self .path }")
            except Exception as e :
                logger .error (f"Failed to load settings: {e }")
                self .data ={}
        else :
            self .data ={}


        self .data =self ._deep_merge (DEFAULTS ,self .data )

        self ._merge_mcp_servers ()

    def save (self ):
        os .makedirs (os .path .dirname (self .path ),exist_ok =True )
        with open (self .path ,"w")as f :
            json .dump (self .data ,f ,indent =2 )

    def get (self ,dotpath :str ,default =None )->Any :
        """Get a nested value using dot notation: 'provider.active'"""
        keys =dotpath .split (".")
        val =self .data 
        for k in keys :
            if isinstance (val ,dict )and k in val :
                val =val [k ]
            else :
                return default 
        return val 

    def set (self ,dotpath :str ,value :Any ):
        """Set a nested value using dot notation: 'provider.gemini.api_key'"""
        keys =dotpath .split (".")
        d =self .data 
        for k in keys [:-1 ]:
            if k not in d or not isinstance (d [k ],dict ):
                d [k ]={}
            d =d [k ]
        d [keys [-1 ]]=value 
        self .save ()

    def get_all (self )->dict :
        return self .data 

    def update_all (self ,new_data :dict ):
        self .data =self ._deep_merge (self .data ,new_data )
        self .save ()

    def get_characters (self )->Dict [str ,Dict ]:
        """Get all available characters (YAML-defined)."""
        return self ._characters 

    def get_active_character (self )->Dict :
        """Get the active character's full definition, falling back to default."""
        active_id =self .get ("character.active","default")
        char =self ._characters .get (active_id )
        if char :
            return char 
        return self ._characters .get ("default",{
        "name":"Assistant",
        "system_prompt":"You are a helpful assistant.",
        "voice":"en-US-AriaNeural",
        "personality":"helpful",
        "characteristics":"helpful, concise",
        "interaction_style":"direct"
        })

    def get_mcp_servers (self )->List [Dict ]:
        """Get configured MCP servers."""
        return self .get ("mcp.servers",[])

    @staticmethod 
    def _deep_merge (base :dict ,override :dict )->dict :
        import copy 
        result =copy .deepcopy (base )
        for k ,v in override .items ():
            if k in result and isinstance (result [k ],dict )and isinstance (v ,dict ):
                result [k ]=Settings ._deep_merge (result [k ],v )
            else :
                result [k ]=copy .deepcopy (v )
        return result 

    def _merge_mcp_servers (self ):
        """Merge DEFAULTS MCP servers into user's list by name.
        New default servers get added; user's enabled/disabled prefs are preserved."""
        defaults_by_name ={s ["name"]:s for s in DEFAULTS .get ("mcp",{}).get ("servers",[])}
        user_servers =self .data .get ("mcp",{}).get ("servers",[])
        user_by_name ={s ["name"]:s for s in user_servers }

        merged =[]
        seen =set ()
        for name ,default in defaults_by_name .items ():
            if name in user_by_name :

                entry =default .copy ()
                entry ["enabled"]=user_by_name [name ].get ("enabled",default .get ("enabled",True ))
                merged .append (entry )
            else :
                merged .append (default .copy ())
            seen .add (name )

        for name ,entry in user_by_name .items ():
            if name not in seen :
                merged .append (entry )

        self .data .setdefault ("mcp",{})["servers"]=merged 
