"""
Web API server — FastAPI + WebSocket for the Amalgam UI.
Serves static frontend files and provides REST API for settings, characters, MCP, etc.
Launch with: python -m backend
"""
import asyncio 
import json 
import logging 
import os 
import sys 

from fastapi import FastAPI ,WebSocket ,WebSocketDisconnect 
from fastapi .staticfiles import StaticFiles 
from fastapi .responses import FileResponse ,JSONResponse 
from fastapi .middleware .cors import CORSMiddleware 

sys .path .insert (0 ,os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ )))))

from backend .config .settings import Settings ,BUILTIN_VOICES 
from backend .core .llm_router import LLMRouter 
from backend .core .memory import Memory 
from backend .core .context_builder import ContextBuilder 
from backend .core .agent import Agent 
from backend .mcp .client import MCPClient 
from backend .voice .tts import TTS 
from backend .voice .pipeline import VoicePipeline 

logging .basicConfig (level =logging .INFO ,format ='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger =logging .getLogger (__name__ )


_shared ={
"settings":None ,
"llm":None ,
"memory":None ,
"context_builder":None ,
"mcp":None ,
"tts":None ,
"agent":None ,
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
        _shared ["memory"]=Memory (llm_router =_shared ["llm"])
    if _shared ["context_builder"]is None :
        _shared ["context_builder"]=ContextBuilder (settings =_shared ["settings"])
    if _shared ["mcp"]is None :
        _shared ["mcp"]=MCPClient ()
    if _shared ["tts"]is None :
        engine =_shared ["settings"].get ("voice.engine","edge-tts")
        _shared ["tts"]=TTS (engine =engine )

        elevenlabs_key =_shared ["settings"].get ("voice.elevenlabs.api_key","")
        if elevenlabs_key :
            elevenlabs_model =_shared ["settings"].get ("voice.elevenlabs.model","eleven_multilingual_v2")
            _shared ["tts"].configure_elevenlabs (elevenlabs_key ,elevenlabs_model )
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
def mcp ():return get_shared ()["mcp"]
def tts ():return get_shared ()["tts"]
def agent ():return get_shared ()["agent"]


app =FastAPI (title ="Amalgam")
app .add_middleware (CORSMiddleware ,allow_origins =["*"],allow_methods =["*"],allow_headers =["*"])




FRONTEND_DIR =os .path .join (os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ )))),"frontend")



PALETTE =[
"#6c5ce7","#0984e3","#00b894","#e17055","#fd79a8",
"#f39c12","#00cec9","#e74c3c","#2ecc71","#3498db",
"#9b59b6","#1abc9c","#d35400","#c0392b","#16a085",
"#8e44ad","#27ae60","#2980b9","#f1c40f","#e67e22",
"#e84393","#00b894","#6c5ce7","#fd79a8","#0984e3",
"#00cec9","#e17055","#f39c12","#e74c3c","#2ecc71",
]


def _generate_letter_icon (name :str ,letter :str ,color_hex :str ,output_path :str ):
    """Generate a 96x96 PNG icon with a colored background and letter."""
    try :
        from PIL import Image ,ImageDraw ,ImageFont 
    except ImportError :
        return False 
    SIZE =96 
    def hex_to_rgb (h ):
        h =h .lstrip ('#')
        return tuple (int (h [i :i +2 ],16 )for i in (0 ,2 ,4 ))
    def lighten (c ,f =0.3 ):
        return tuple (int (v +(255 -v )*f )for v in c )
    def darken (c ,f =0.3 ):
        return tuple (int (v *(1 -f ))for v in c )
    bg =hex_to_rgb (color_hex )
    img =Image .new ('RGBA',(SIZE ,SIZE ),(0 ,0 ,0 ,0 ))
    draw =ImageDraw .Draw (img )
    draw .rounded_rectangle ([0 ,0 ,SIZE -1 ,SIZE -1 ],radius =16 ,fill =bg )
    highlight =lighten (bg ,0.25 )
    draw .rounded_rectangle ([2 ,2 ,SIZE -3 ,SIZE -3 ],radius =14 ,fill =highlight +(30 ,))
    try :
        font =ImageFont .truetype ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",44 )
    except (IOError ,OSError ):
        font =ImageFont .load_default ()
    bbox =draw .textbbox ((0 ,0 ),letter ,font =font )
    tw ,th =bbox [2 ]-bbox [0 ],bbox [3 ]-bbox [1 ]
    x =(SIZE -tw )/2 -bbox [0 ]
    y =(SIZE -th )/2 -bbox [1 ]-2 
    draw .text ((x +1 ,y +1 ),letter ,fill =darken (bg ,0.4 )+(100 ,),font =font )
    draw .text ((x ,y ),letter ,fill =(255 ,255 ,255 ,230 ),font =font )
    img .save (output_path ,'PNG')
    return True 


async def _generate_missing_icons ():
    """Generate icons for characters missing icon.png. Tries VRM renderer first, falls back to letters."""

    if not os .path .exists (CHARACTERS_DIR ):
        return 
    missing =[]
    for d in sorted (os .listdir (CHARACTERS_DIR )):
        char_path =os .path .join (CHARACTERS_DIR ,d )
        if os .path .isdir (char_path )and not os .path .exists (os .path .join (char_path ,"icon.png")):
            missing .append (d )
    if not missing :
        return 
    logger .info (f"Missing icons for {len (missing )} character(s): {', '.join (missing )}")


    import shutil 
    node =shutil .which ("node")
    vrm_script =os .path .join (os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ )))),"scripts","generate-icons-vrm.js")
    if node and os .path .exists (vrm_script ):
        try :
            proc =await asyncio .create_subprocess_exec (
            node ,vrm_script ,
            stdout =asyncio .subprocess .PIPE ,
            stderr =asyncio .subprocess .PIPE ,
            cwd =os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ ))))
            )
            stdout ,stderr =await asyncio .wait_for (proc .communicate (),timeout =300 )
            if proc .returncode ==0 :
                logger .info ("VRM icon generation complete")
                return 
            else :
                logger .warning (f"VRM icon generation failed (exit {proc .returncode })")
        except Exception as e :
            logger .warning (f"VRM icon generation error: {e }")


    loop =asyncio .get_event_loop ()
    await loop .run_in_executor (None ,_generate_missing_icons_sync )


def _generate_missing_icons_sync ():
    """Sync icon generation for missing characters."""
    try :
        import yaml 
    except ImportError :
        return 
    char_dirs =sorted ([
    d for d in os .listdir (CHARACTERS_DIR )
    if os .path .isdir (os .path .join (CHARACTERS_DIR ,d ))
    ])
    generated =0 
    for idx ,char_dir in enumerate (char_dirs ):
        icon_path =os .path .join (CHARACTERS_DIR ,char_dir ,"icon.png")
        if os .path .exists (icon_path ):
            continue 
        index_path =os .path .join (CHARACTERS_DIR ,char_dir ,"index.yaml")
        name =char_dir 
        if os .path .exists (index_path ):
            try :
                with open (index_path ,'r')as f :
                    data =yaml .safe_load (f )or {}
                name =data .get ('name',char_dir )
            except Exception :
                pass 
        letter =name [0 ].upper ()if name else '?'
        color =PALETTE [idx %len (PALETTE )]
        if _generate_letter_icon (name ,letter ,color ,icon_path ):
            generated +=1 
    if generated :
        logger .info (f"Generated {generated } character icon(s)")


async def _delayed_startup_tasks ():
    try :
        await asyncio .sleep (2.0 )
        await _generate_missing_icons ()
    except Exception as e :
        logger .error (f"Error in delayed startup tasks: {e }")


@app .on_event ("startup")
async def startup ():
    logger .info ("Starting Amalgam backend...")
    asyncio .create_task (_delayed_startup_tasks ())

    memory ().start_session ()

    engine =settings ().get ("voice.engine","edge-tts")
    if engine =="openvoice":
        logger .info ("Preloading OpenVoice TTS engine...")
        try :
            loop =asyncio .get_event_loop ()
            await loop .run_in_executor (None ,tts ().get_openvoice_loaded )
            logger .info ("OpenVoice TTS engine ready")
        except Exception as e :
            logger .warning (f"OpenVoice preload failed: {e }")

    vault_path =settings ().get ("vault.path","user_data/vault")
    os .makedirs (vault_path ,exist_ok =True )


    rules_path =os .path .join (vault_path ,"rules.md")
    if not os .path .exists (rules_path ):
        with open (rules_path ,"w")as f :
            f .write ("# Rules\n\nAdd your custom rules here. These will be injected into every conversation.\n")


    mcp_servers =settings ().get_mcp_servers ()
    if mcp_servers :
        try :
            await mcp ().connect_from_settings (mcp_servers )
        except Exception as e :
            logger .warning (f"MCP servers from settings failed: {e }")
    else :
        try :
            await mcp ().connect_servers ("backend/config/mcp_servers.json")
        except Exception as e :
            logger .warning (f"MCP servers from file failed: {e }")


@app .get ("/")
async def index ():
    return FileResponse (os .path .join (FRONTEND_DIR ,"index.html"))



CHAR_DEFAULT_ANIM =os .path .join (os .path .dirname (FRONTEND_DIR ),"characters","default","anim")
if os .path .exists (CHAR_DEFAULT_ANIM ):
    app .mount ("/static/animations",StaticFiles (directory =CHAR_DEFAULT_ANIM ),name ="default_animations")


if os .path .exists (FRONTEND_DIR ):
    app .mount ("/static",StaticFiles (directory =FRONTEND_DIR ),name ="static")


USER_DATA_DIR =os .path .join (os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ )))),"user_data")
if os .path .exists (USER_DATA_DIR ):
    app .mount ("/user_data",StaticFiles (directory =USER_DATA_DIR ),name ="user_data")


CHARACTERS_DIR =os .path .join (os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ )))),"characters")
if os .path .exists (CHARACTERS_DIR ):
    app .mount ("/characters",StaticFiles (directory =CHARACTERS_DIR ),name ="characters")




@app .get ("/api/settings")
async def get_settings ():
    return settings ().get_all ()


@app .post ("/api/settings")
async def update_settings (body :dict ):
    settings ().update_all (body )
    llm ().reload_settings ()
    engine =settings ().get ("voice.engine","edge-tts")
    tts ().engine =engine 

    if engine =="elevenlabs":
        elevenlabs_key =settings ().get ("voice.elevenlabs.api_key","")
        if elevenlabs_key :
            elevenlabs_model =settings ().get ("voice.elevenlabs.model","eleven_multilingual_v2")
            tts ().configure_elevenlabs (elevenlabs_key ,elevenlabs_model )
    elif engine =="openai-tts":
        oa_key =settings ().get ("voice.openai_tts.api_key","")
        oa_model =settings ().get ("voice.openai_tts.model","tts-1")
        oa_url =settings ().get ("voice.openai_tts.base_url",None )
        if oa_key :
            tts ().configure_openai_tts (oa_key ,oa_model ,oa_url )
    elif engine =="alltalk":
        url =settings ().get ("voice.alltalk.url",None )
        lang =settings ().get ("voice.alltalk.language","en")
        ver =settings ().get ("voice.alltalk.version","v2")
        rv =settings ().get ("voice.alltalk.rvc_voice","")
        rp =settings ().get ("voice.alltalk.rvc_pitch","0")
        tts ().configure_alltalk (url ,lang ,ver ,rv ,rp )
    elif engine =="piper":
        url =settings ().get ("voice.piper.url",None )
        tts ().configure_piper (url )
    elif engine =="coqui-local":
        url =settings ().get ("voice.coqui_local.url",None )
        sid =settings ().get ("voice.coqui_local.speaker_id","")
        tts ().configure_coqui (url ,sid )
    elif engine =="kokoro":
        url =settings ().get ("voice.kokoro.url",None )
        tts ().configure_kokoro (url )
    _sync_emotion_tags ()
    agent ().update_settings (settings ())


    if "character"in body and "active"in body ["character"]:
        char_id =body ["character"]["active"]
        chars =settings ().get_characters ()
        if char_id in chars :
            logger .info (f"Character switched to {chars [char_id ].get ('name',char_id )}")

    return {"status":"ok","voice":tts ().voice }


@app .post ("/api/settings/set")
async def set_setting (body :dict ):
    key =body .get ("key")
    value =body .get ("value")
    if key :
        settings ().set (key ,value )
        llm ().reload_settings ()
        _sync_emotion_tags ()
        agent ().update_settings (settings ())
    return {"status":"ok"}




@app .get ("/api/characters")
async def get_characters ():
    """Return all available characters with their full definitions."""
    return settings ().get_characters ()


@app .get ("/api/characters/{character_id}")
async def get_character (character_id :str ):
    """Get a specific character's definition."""
    chars =settings ().get_characters ()
    if character_id in chars :
        return chars [character_id ]
    return JSONResponse (status_code =404 ,content ={"error":"Character not found"})




PROJECT_ROOT =os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ ))))


@app .get ("/api/animations")
async def get_animations (char_id :str =None ):
    """Return available VRMA animation files.
    Merges default/anim/*.vrma with per-character animations from
    characters/<char_id>/anim/*.vrma if char_id is provided.
    """
    default_dir =os .path .join (PROJECT_ROOT ,"characters","default","anim")
    animations ={"default":[],"character":[]}

    if os .path .exists (default_dir ):
        for f in sorted (os .listdir (default_dir )):
            if f .endswith (".vrma"):
                name =f .replace (".vrma","").replace (".bvh","")
                animations ["default"].append ({
                "file":f ,
                "name":name ,
                "url":f"/static/animations/{f }"
                })

    if char_id and char_id !="default":
        char_anim_dir =os .path .join (PROJECT_ROOT ,"characters",char_id ,"anim")
        if os .path .exists (char_anim_dir ):
            for f in sorted (os .listdir (char_anim_dir )):
                if f .endswith (".vrma"):
                    name =f .replace (".vrma","").replace (".bvh","")
                    animations ["character"].append ({
                    "file":f ,
                    "name":name ,
                    "url":f"/characters/{char_id }/anim/{f }"
                    })

    return animations 


@app .get ("/api/emotions")
async def get_emotions ():
    return {"emotions":tts ().get_supported_emotions ()}


@app .get ("/api/expressions")
async def get_expressions (char_id :str =None ):
    from backend .core .context_builder import VRM_EXPRESSIONS 
    exprs =list (VRM_EXPRESSIONS )
    return {"expressions":exprs }




@app .get ("/api/voices")
async def get_voices ():
    return BUILTIN_VOICES 




@app .get ("/api/models/ollama")
async def get_ollama_models ():
    models =await llm ().fetch_ollama_models ()
    return {"models":models }


@app .get ("/api/models/gemini")
async def get_gemini_models ():
    models =await llm ().fetch_gemini_models ()
    return {"models":models }


@app .get ("/api/models/{provider}")
async def get_provider_models (provider :str ):
    if provider =="ollama":
        models =await llm ().fetch_ollama_models ()
        return {"models":models }
    if provider =="gemini":
        models =await llm ().fetch_gemini_models ()
        return {"models":models }
    if provider in LLMRouter .OPENAI_COMPAT :
        fresh_llm =LLMRouter (settings =settings ())
        models =await fresh_llm .fetch_openai_compat_models (provider )
        await fresh_llm .close ()
        return {"models":models }
    if provider =="claude":
        return {"models":["claude-sonnet-4-20250514","claude-3-5-sonnet-20241022",
        "claude-3-opus-20240229","claude-3-haiku-20240307"]}
    return JSONResponse (status_code =400 ,content ={"error":f"Unknown provider: {provider }"})




@app .post ("/api/icons/regenerate")
async def regenerate_icons ():
    """Regenerate character icons. Tries VRM renderer (Node.js + Chrome) first,
    then fills in letter-based icons for any characters VRM couldn't handle."""
    import shutil 
    project_root =os .path .dirname (os .path .dirname (os .path .dirname (os .path .abspath (__file__ ))))
    vrm_output =""
    vrm_ok =False 


    char_dirs =sorted ([
    d for d in os .listdir (CHARACTERS_DIR )
    if os .path .isdir (os .path .join (CHARACTERS_DIR ,d ))
    ])
    for char_dir in char_dirs :
        icon_path =os .path .join (CHARACTERS_DIR ,char_dir ,"icon.png")
        if os .path .exists (icon_path ):
            os .remove (icon_path )


    node =shutil .which ("node")
    vrm_script =os .path .join (project_root ,"scripts","generate-icons-vrm.js")
    if node and os .path .exists (vrm_script ):
        try :
            logger .info ("Running VRM icon generation...")
            proc =await asyncio .create_subprocess_exec (
            node ,vrm_script ,"--all",
            stdout =asyncio .subprocess .PIPE ,
            stderr =asyncio .subprocess .PIPE ,
            cwd =project_root 
            )
            stdout ,stderr =await asyncio .wait_for (proc .communicate (),timeout =300 )
            vrm_output =stdout .decode ()+stderr .decode ()
            vrm_ok =proc .returncode ==0 
            logger .info (f"VRM icon gen result (ok={vrm_ok }): {vrm_output }")
        except Exception as e :
            logger .error (f"VRM icon generation crashed: {e }")



    _generate_missing_icons_sync ()

    return {
    "status":"ok",
    "method":"vrm+letter"if vrm_ok else "letter",
    "vrm_output":vrm_output if vrm_output else None ,
    }




@app .get ("/api/mcp/servers")
async def get_mcp_servers ():
    """Get configured MCP servers and their status."""
    servers =settings ().get_mcp_servers ()
    connected =list (mcp ().sessions .keys ())if mcp ()else []
    result =[]
    for s in servers :
        result .append ({
        **s ,
        "connected":s ["name"]in connected 
        })
    return {"servers":result }


@app .post ("/api/mcp/servers")
async def update_mcp_servers (body :dict ):
    """Update MCP server configuration."""
    servers =body .get ("servers",[])
    settings ().set ("mcp.servers",servers )
    return {"status":"ok","message":"MCP settings saved. Restart to apply changes."}


@app .get ("/api/mcp/tools")
async def get_mcp_tools ():
    """Get all available MCP tools."""
    tools =mcp ().get_tool_schema ()if mcp ()else []
    return {"tools":tools }




@app .get ("/api/rules")
async def get_rules ():
    vault_path =settings ().get ("vault.path","user_data/vault")
    rules_path =os .path .join (vault_path ,"rules.md")
    if os .path .exists (rules_path ):
        with open (rules_path ,"r")as f :
            return {"content":f .read ()}
    return {"content":""}


@app .post ("/api/rules")
async def save_rules (body :dict ):
    vault_path =settings ().get ("vault.path","user_data/vault")
    os .makedirs (vault_path ,exist_ok =True )
    rules_path =os .path .join (vault_path ,"rules.md")
    with open (rules_path ,"w")as f :
        f .write (body .get ("content",""))
    return {"status":"ok"}


@app .get ("/api/vault/files")
async def list_vault_files ():
    vault_path =settings ().get ("vault.path","user_data/vault")
    if not os .path .exists (vault_path ):
        return {"files":[]}
    files =[]
    for f in os .listdir (vault_path ):
        fp =os .path .join (vault_path ,f )
        if os .path .isfile (fp ):
            files .append ({"name":f ,"size":os .path .getsize (fp )})
    return {"files":files }




@app .get ("/api/memory/sessions")
async def get_sessions ():
    sessions =memory ().get_sessions ()
    return {"sessions":sessions }

@app .get ("/api/memory/session/{session_id}")
async def get_session_messages (session_id :str ):
    messages =memory ().get_session_messages (session_id )
    return {"messages":messages }

@app .delete ("/api/memory/session/{session_id}")
async def delete_session (session_id :str ):
    memory ().delete_session (session_id )
    return {"status":"ok"}

@app .post ("/api/memory/clear")
async def clear_memory ():
    memory ().clear ()
    memory ().start_session ()
    return {"status":"ok"}

@app .get ("/api/memory/session/current")
async def get_current_session ():
    sid =memory ().get_current_session ()
    messages =memory ().get_session_messages (sid )
    return {"session_id":sid ,"messages":messages }

@app .post ("/api/memory/new-session")
async def new_session ():
    sid =memory ().start_session ()
    return {"session_id":sid }




async def _synthesize_now (text :str ,ws :WebSocket ):
    """Synthesize TTS for text and send audio directly (used by speak button)."""
    import base64 ,struct 
    try :
        char =settings ().get_active_character ()
        ref_audio =None 
        if tts ().engine =="openvoice":
            ref_audio =char .get ("voice_ref")if char else None 
            if not ref_audio :
                char_dir =char .get ("_dir","")if char else ""
                if char_dir :
                    candidate =os .path .join (char_dir ,"ref.wav")
                    if os .path .exists (candidate ):
                        ref_audio =candidate 
            if not ref_audio :
                logger .warning ("No voice_ref for OpenVoice, skipping speak")
                return 
        result =await asyncio .wait_for (tts ().synthesize (text ,ref_audio =ref_audio ),timeout =60.0 )
        audio_np ,_ ,sr =result 
        if len (audio_np )>0 :
            pcm =(audio_np *32767 ).astype ("int16").tobytes ()
            data_size =len (pcm )
            header =struct .pack (
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',36 +data_size ,b'WAVE',
            b'fmt ',16 ,1 ,1 ,sr ,sr *1 *16 //8 ,
            1 *16 //8 ,16 ,
            b'data',data_size 
            )
            wav_bytes =header +pcm 
            b64 =base64 .b64encode (wav_bytes ).decode ()
            duration =len (audio_np )/sr 
            await ws .send_json ({
            "type":"tts_audio","audio":b64 ,"format":"wav",
            "duration":round (duration ,2 ),"sentence_idx":0 ,"emotion":"neutral"
            })
            logger .info (f"Speak TTS: sent {duration :.2f}s audio")
        else :
            logger .warning ("Speak TTS: empty audio")
    except asyncio .TimeoutError :
        logger .error ("Speak TTS: timed out")
    except Exception as e :
        logger .error (f"Speak TTS error: {e }")

@app .websocket ("/ws/chat")
async def ws_chat (websocket :WebSocket ):
    await websocket .accept ()
    logger .info ("Chat WebSocket connected")
    voice_output_enabled =False 
    voice_pipeline =None 
    voice_task =None 
    _stream_idx =0 

    try :
        while True :
            data =await websocket .receive_json ()
            msg_type =data .get ("type")

            if msg_type =="command":
                cmd =data .get ("command","")
                if cmd in ("voice_output_on","voice_on"):
                    voice_output_enabled =True 
                    logger .info ("Voice output enabled by client")
                    await websocket .send_json ({"type":"voice_state","state":"idle"})
                elif cmd in ("voice_output_off","voice_off"):
                    voice_output_enabled =False 
                    logger .info ("Voice output disabled by client")
                    await websocket .send_json ({"type":"voice_state","state":"idle"})
                elif cmd =="voice_input_on":
                    if voice_pipeline is None :
                        _main_loop =asyncio .get_running_loop ()
                        def on_transcription (text ):
                            """Callback from VoicePipeline thread — fire-and-forget to websocket."""
                            try :
                                asyncio .run_coroutine_threadsafe (
                                websocket .send_json ({"type":"user_message_from_voice","text":text }),
                                _main_loop 
                                )
                            except Exception as e :
                                logger .warning (f"Voice transcription send failed: {e }")
                        stt_engine =settings ().get ("voice.stt_engine","faster-whisper")
                        voice_pipeline =VoicePipeline (agent_callback =on_transcription ,stt_engine =stt_engine )

                        if stt_engine =="openai-whisper":
                            whisper_key =settings ().get ("voice.openai_whisper.api_key","")
                            if whisper_key :
                                whisper_model =settings ().get ("voice.openai_whisper.model","whisper-1")
                                voice_pipeline .configure_openai_stt (whisper_key ,whisper_model )
                        elif stt_engine =="groq-whisper":
                            groq_key =settings ().get ("voice.groq_whisper.api_key","")
                            if groq_key :
                                groq_model =settings ().get ("voice.groq_whisper.model","whisper-large-v3")
                                groq_url =settings ().get ("voice.groq_whisper.base_url",None )
                                voice_pipeline .configure_groq_stt (groq_key ,groq_model ,groq_url )
                        elif stt_engine =="whispercpp":
                            wcpp_url =settings ().get ("voice.whispercpp.url",None )
                            voice_pipeline .configure_whispercpp_stt (wcpp_url )
                    if voice_task is None or voice_task .done ():
                        if voice_task and voice_task .exception ():
                            logger .error (f"Previous voice task failed: {voice_task .exception ()}")
                        voice_task =asyncio .get_event_loop ().run_in_executor (None ,voice_pipeline .listen_loop )
                    await websocket .send_json ({"type":"voice_state","state":"recording"})
                    logger .info ("Voice input started")
                elif cmd =="voice_input_off":
                    if voice_pipeline :
                        voice_pipeline .stop_listening ()
                    if voice_task and not voice_task .done ():
                        voice_task .cancel ()
                        voice_task =None 
                    voice_pipeline =None 
                    await websocket .send_json ({"type":"voice_state","state":"idle"})
                    logger .info ("Voice input stopped")
                elif cmd =="speak":
                    speak_text =data .get ("text","").strip ()
                    if speak_text :
                        logger .info (f"Speak command: {speak_text [:50 ]}")
                        asyncio .create_task (_synthesize_now (speak_text ,websocket ))
                continue 

            if msg_type =="user_message":
                text =data .get ("text","").strip ()
                images =data .get ("images",None )
                if not text and not images :
                    continue 

                if text =="/clear":
                    memory ().clear ()
                    memory ().start_session ()
                    await websocket .send_json (
                    {"type":"chat_append","role":"system","text":"Memory cleared.","finished":True })
                    continue 

                if text =="/help":
                    help_text ="Commands:\n/clear — clear history\n/help — show this"
                    await websocket .send_json (
                    {"type":"chat_append","role":"system","text":help_text ,"finished":True })
                    continue 


                await websocket .send_json ({"type":"chat_start","role":"assistant"})
                await websocket .send_json ({"type":"emotion","emotion":"neutral"})
                await websocket .send_json ({"type":"expression","expression":"neutral"})


                _stream_idx +=1 
                current_stream =_stream_idx 

                try :
                    import base64 as _b64 
                    import struct as _struct 
                    import re as _re 
                    full_response =""
                    sentence_buffer =""
                    sentence_idx =0 
                    current_emotion ="neutral"
                    lipsync_on =settings ().get ("voice.lipsync_enabled",True )


                    if voice_output_enabled :
                        char =settings ().get_active_character ()
                        if tts ().engine !="openvoice":
                            char_voice =char .get ("voice","en-US-AriaNeural")if char else "en-US-AriaNeural"
                            if tts ().voice !=char_voice :
                                tts ().voice =char_voice 

                    async def synthesize_and_send (sentence_text ,idx ,stream_id ,emotion ="neutral"):
                        """TTS a single sentence and send audio over WebSocket."""
                        nonlocal sentence_idx 
                        try :

                            if stream_id !=_stream_idx :
                                logger .info (f"TTS sentence {idx }: skipped (stale stream)")
                                return 
                            char =settings ().get_active_character ()
                            ref_audio =None 
                            if tts ().engine =="openvoice":
                                ref_audio =char .get ("voice_ref")if char else None 
                                if not ref_audio :
                                    char_dir =char .get ("_dir","")if char else ""
                                    if char_dir :
                                        candidate =os .path .join (char_dir ,"ref.wav")
                                        if os .path .exists (candidate ):
                                            ref_audio =candidate 
                                if not ref_audio :
                                    logger .warning ("No voice_ref for OpenVoice, skipping TTS")
                                    return 
                            result =await asyncio .wait_for (
                            tts ().synthesize (sentence_text ,ref_audio =ref_audio ),
                            timeout =60.0 
                            )
                            audio_np ,_ ,sr =result 
                            logger .info (f"TTS sentence {idx }: {len (audio_np )} samples, sr={sr }")
                            if len (audio_np )>0 :
                                pcm =(audio_np *32767 ).astype ("int16").tobytes ()
                                data_size =len (pcm )
                                header =_struct .pack (
                                '<4sI4s4sIHHIIHH4sI',
                                b'RIFF',36 +data_size ,b'WAVE',
                                b'fmt ',16 ,1 ,1 ,sr ,sr *1 *16 //8 ,
                                1 *16 //8 ,16 ,
                                b'data',data_size 
                                )
                                wav_bytes =header +pcm 
                                b64 =_b64 .b64encode (wav_bytes ).decode ()
                                duration =len (audio_np )/sr 
                                await websocket .send_json ({
                                "type":"tts_audio",
                                "audio":b64 ,
                                "format":"wav",
                                "duration":round (duration ,2 ),
                                "sentence_idx":idx ,
                                "emotion":emotion 
                                })
                                logger .info (f"TTS sentence {idx }: sent {duration :.2f}s audio (emotion={emotion })")
                            else :
                                logger .warning (f"TTS sentence {idx }: empty audio")
                        except asyncio .TimeoutError :
                            logger .error (f"TTS sentence {idx }: timed out after 60s")
                        except Exception as tts_err :
                            logger .error (f"TTS error for sentence {idx }: {type (tts_err ).__name__ }: {tts_err }")


                    tts_tasks =[]

                    async for item in agent ().handle_user_input (text ,images =images ):

                        if isinstance (item ,tuple )and item [0 ]=='__emotion__':
                            current_emotion =item [1 ]
                            try :
                                await websocket .send_json ({"type":"emotion","emotion":current_emotion })
                            except WebSocketDisconnect :
                                raise 
                            except Exception :
                                pass 
                            continue 

                        if isinstance (item ,tuple )and item [0 ]=='__expression__':
                            try :
                                await websocket .send_json ({"type":"expression","expression":item [1 ]})
                            except WebSocketDisconnect :
                                raise 
                            except Exception :
                                pass 
                            continue 

                        if isinstance (item ,tuple )and item [0 ]=='__thinking__':
                            try :
                                await websocket .send_json ({"type":"thinking","text":item [1 ]})
                            except WebSocketDisconnect :
                                raise 
                            except Exception :
                                pass 
                            continue 

                        if isinstance (item ,tuple )and item [0 ]=='__roleplay__':
                            rp_text =f"*{item [1 ]}* "
                            full_response +=rp_text 
                            sentence_buffer +=rp_text 
                            try :
                                await websocket .send_json ({"type":"roleplay","text":item [1 ]})
                            except WebSocketDisconnect :
                                raise 
                            except Exception :
                                pass 
                            continue 

                        token =item 
                        full_response +=token 
                        sentence_buffer +=token 
                        try :
                            await websocket .send_json ({
                            "type":"chat_append",
                            "role":"assistant",
                            "text":token ,
                            "finished":False 
                            })
                        except WebSocketDisconnect :
                            raise 
                        except Exception :
                            pass 





                        if voice_output_enabled and _re .search (r'[.!?。！？]\s|[.!?。！？]$|,\s{10,}',sentence_buffer ):

                            parts =_re .split (r'(?<=[.!?。！？])\s',sentence_buffer )
                            if len (parts )>1 :
                                complete =parts [0 ].strip ()
                                sentence_buffer =' '.join (parts [1 :])
                                if complete :
                                    try :
                                        await websocket .send_json ({"type":"voice_state","state":"speaking"})
                                    except WebSocketDisconnect :
                                        raise 
                                    except Exception :
                                        pass 
                                    task =asyncio .create_task (synthesize_and_send (complete ,sentence_idx ,current_stream ,current_emotion ))
                                    tts_tasks .append (task )
                                    sentence_idx +=1 


                    try :
                        await websocket .send_json ({"type":"viseme","value":0.0 })
                    except WebSocketDisconnect :
                        raise 
                    except Exception :
                        pass 


                    if voice_output_enabled and sentence_buffer .strip ():
                        try :
                            await websocket .send_json ({"type":"voice_state","state":"speaking"})
                        except WebSocketDisconnect :
                            raise 
                        except Exception :
                            pass 
                        task =asyncio .create_task (synthesize_and_send (sentence_buffer .strip (),sentence_idx ,current_stream ,current_emotion ))
                        tts_tasks .append (task )
                        sentence_idx +=1 


                    if tts_tasks :
                        await asyncio .gather (*tts_tasks ,return_exceptions =True )
                        try :
                            await websocket .send_json ({"type":"voice_state","state":"idle"})
                        except Exception :
                            pass 

                except Exception as e :
                    logger .error (f"Agent error: {e }")

                    for t in tts_tasks :
                        if not t .done ():
                            t .cancel ()
                    error_text =str (e )

                    friendly_errors ={
                    "content must be a string":"This provider doesn't support image input. Try a different model or remove the image.",
                    "content must be a non-empty string":"This provider doesn't support image input. Try a different model or remove the image.",
                    "unsupported image format":"The image format is not supported. Try a different image.",
                    "image_url is not supported":"This provider doesn't support image input. Try a different model or remove the image.",
                    "API key not set":"API key not configured. Go to Settings > Providers to set it.",
                    "401":"Authentication failed. Check your API key.",
                    "402":"Payment required. Check your account billing.",
                    "429":"Rate limit exceeded. Please wait and try again.",
                    "RESOURCE_EXHAUSTED":"Quota exceeded. Check your plan and billing."
                    }
                    for key ,msg in friendly_errors .items ():
                        if key .lower ()in error_text .lower ():
                            error_text =msg 
                            break 

                    try :
                        import json as _json 
                        if error_text .startswith ('{'):
                            err_obj =_json .loads (error_text )
                            error_text =err_obj .get ('message',error_text )
                    except Exception :
                        pass 
                    await websocket .send_json ({
                    "type":"chat_append",
                    "role":"assistant",
                    "text":f"Error: {error_text }",
                    "finished":True ,
                    "error":True 
                    })
                else :
                    try :
                        await websocket .send_json ({"type":"emotion","emotion":"neutral"})
                        await websocket .send_json ({"type":"expression","expression":"neutral"})
                        await websocket .send_json ({
                        "type":"chat_append",
                        "role":"assistant",
                        "text":"",
                        "finished":True 
                        })
                    except WebSocketDisconnect :
                        raise 
                    except Exception :
                        pass 

    except WebSocketDisconnect :
        logger .info ("Chat WebSocket disconnected")
    except Exception as e :
        logger .error (f"WebSocket error: {e }")
    finally :
        if voice_pipeline :
            voice_pipeline .stop_listening ()
        if voice_task and not voice_task .done ():
            voice_task .cancel ()




@app .post ("/api/tts/preview")
async def tts_preview (body :dict ):
    text =body .get ("text","Hello, I am your assistant.")
    engine =settings ().get ("voice.engine","edge-tts")
    char =settings ().get_active_character ()

    if engine =="openvoice":
        ref_audio =char .get ("voice_ref")if char else None 
        if not ref_audio :
            char_dir =char .get ("_dir","")if char else ""
            if char_dir :
                candidate =os .path .join (char_dir ,"ref.wav")
                if os .path .exists (candidate ):
                    ref_audio =candidate 
        if not ref_audio :
            return {"audio":None ,"error":"No voice_ref set. Place a ref.wav in the character directory."}
        temp_tts =TTS (engine ="openvoice")
        audio ,_ ,sr =await temp_tts .synthesize (text ,ref_audio =ref_audio )
    else :
        voice =char .get ("voice","en-US-AriaNeural")if char else "en-US-AriaNeural"
        temp_tts =TTS (voice =voice )
        audio ,_ ,sr =await temp_tts .synthesize (text )

    if len (audio )>0 :
        import base64 
        import struct 
        pcm =(audio *32767 ).astype ("int16").tobytes ()
        nch =1 
        bps =16 
        data_size =len (pcm )
        header =struct .pack ('<4sI4s4sIHHIIHH4sI',
        b'RIFF',36 +data_size ,b'WAVE',
        b'fmt ',16 ,1 ,nch ,sr ,sr *nch *bps //8 ,nch *bps //8 ,bps ,
        b'data',data_size )
        wav_bytes =header +pcm 
        b64 =base64 .b64encode (wav_bytes ).decode ()
        return {"audio":b64 ,"format":"wav"}
    return {"audio":None }
