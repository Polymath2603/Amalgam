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
        _shared ["tts"]=TTS (engine =_shared ["settings"].get ("voice.engine","edge-tts"))
    if _shared ["agent"]is None :
        _shared ["agent"]=Agent (
        mcp_client =_shared ["mcp"],
        llm =_shared ["llm"],
        memory =_shared ["memory"],
        context_builder =_shared ["context_builder"],
        settings =_shared ["settings"]
        )
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


@app .on_event ("startup")
async def startup ():
    logger .info ("Starting Amalgam backend...")

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
    tts ().engine =settings ().get ("voice.engine","edge-tts")
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
    return JSONResponse (status_code =400 ,content ={"error":f"Unknown provider: {provider }"})




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

@app .post ("/api/memory/new-session")
async def new_session ():
    sid =memory ().start_session ()
    return {"session_id":sid }




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
                        loop =asyncio .get_event_loop ()
                        def on_transcription (text ):
                            """Callback from VoicePipeline thread — safely send to websocket."""
                            try :
                                future =asyncio .run_coroutine_threadsafe (
                                websocket .send_json ({"type":"user_message_from_voice","text":text }),
                                loop 
                                )
                                future .result (timeout =5 )
                            except Exception as e :
                                logger .warning (f"Voice transcription send failed: {e }")
                        voice_pipeline =VoicePipeline (agent_callback =on_transcription )
                    if voice_task is None or voice_task .done ():
                        voice_task =asyncio .create_task (
                        asyncio .get_event_loop ().run_in_executor (None ,voice_pipeline .listen_loop )
                        )
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
                continue 

            if msg_type =="user_message":
                text =data .get ("text","").strip ()
                if not text :
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
                await websocket .send_json ({"type":"emotion","emotion":"thinking"})


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

                    async def synthesize_and_send (sentence_text ,idx ,stream_id ):
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
                                "sentence_idx":idx 
                                })
                                logger .info (f"TTS sentence {idx }: sent {duration :.2f}s audio")
                            else :
                                logger .warning (f"TTS sentence {idx }: empty audio")
                        except asyncio .TimeoutError :
                            logger .error (f"TTS sentence {idx }: timed out after 60s")
                        except Exception as tts_err :
                            logger .error (f"TTS error for sentence {idx }: {type (tts_err ).__name__ }: {tts_err }")


                    tts_tasks =[]

                    async for item in agent ().handle_user_input (text ):

                        if isinstance (item ,tuple )and item [0 ]=='__emotion__':
                            current_emotion =item [1 ]
                            await websocket .send_json ({"type":"emotion","emotion":current_emotion })
                            continue 

                        if isinstance (item ,tuple )and item [0 ]=='__thinking__':
                            await websocket .send_json ({"type":"thinking","text":item [1 ]})
                            continue 

                        token =item 
                        full_response +=token 
                        sentence_buffer +=token 
                        await websocket .send_json ({
                        "type":"chat_append",
                        "role":"assistant",
                        "text":token ,
                        "finished":False 
                        })


                        if lipsync_on and token .strip ():
                            import random as _rand 
                            length_factor =min (1.0 ,len (token .strip ())/8 )
                            if token .strip ()[-1 ]in '.!?,;:':
                                viseme_val =0.0 
                            else :
                                viseme_val =0.2 +length_factor *0.5 +_rand .uniform (-0.1 ,0.1 )
                            await websocket .send_json ({"type":"viseme","value":round (max (0 ,min (1 ,viseme_val )),2 )})


                        if voice_output_enabled and _re .search (r'[.!?。！？]\s|[.!?。！？]$|,\s{10,}',sentence_buffer ):

                            parts =_re .split (r'(?<=[.!?。！？])\s',sentence_buffer )
                            if len (parts )>1 :
                                complete =parts [0 ].strip ()
                                sentence_buffer =' '.join (parts [1 :])
                                if complete :
                                    await websocket .send_json ({"type":"voice_state","state":"speaking"})
                                    task =asyncio .create_task (synthesize_and_send (complete ,sentence_idx ,current_stream ))
                                    tts_tasks .append (task )
                                    sentence_idx +=1 


                    await websocket .send_json ({"type":"viseme","value":0.0 })


                    if voice_output_enabled and sentence_buffer .strip ():
                        await websocket .send_json ({"type":"voice_state","state":"speaking"})
                        task =asyncio .create_task (synthesize_and_send (sentence_buffer .strip (),sentence_idx ,current_stream ))
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
                    error_text =str (e )

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
                    await websocket .send_json ({"type":"emotion","emotion":"neutral"})
                    await websocket .send_json ({
                    "type":"chat_append",
                    "role":"assistant",
                    "text":"",
                    "finished":True 
                    })

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
