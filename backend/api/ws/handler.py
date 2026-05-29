"""
WebSocket chat handler — per-connection state, proper task tracking.
"""
import asyncio 
import json 
import re 
import logging 

from fastapi import WebSocket ,WebSocketDisconnect 
from backend .api .deps import settings ,memory ,tts ,agent ,relationship 
from backend .api .ws .tts_service import synthesize_sentence ,synthesize_now 
from pathlib import Path 
from backend .core .paths import CHARACTERS_DIR ,PROJECT_ROOT 
from backend .voice .pipeline import VoicePipeline 

logger =logging .getLogger (__name__ )


def _normalize_error (error_text :str )->str :
    """Normalize common error messages to user-friendly versions."""
    import re as _re 

    m =_re .search (r'\{.*\}',error_text ,_re .DOTALL )
    if m :
        try :
            obj =json .loads (m .group ())
            inner =obj .get ('error',obj )
            if isinstance (inner ,dict ):
                msg =inner .get ('message','')
                if msg :
                    error_text =msg 
        except Exception :
            pass 

    friendly ={
    "rate limit":"Rate limit exceeded. Please wait and try again.",
    "quota exceeded":"Quota exceeded. Check your plan and billing.",
    "RESOURCE_EXHAUSTED":"Quota exceeded. Check your plan and billing.",
    "API key not set":"API key not configured. Go to Settings > Providers to set it.",
    "content must be a string":"This provider doesn't support image input. Try a different model or remove the image.",
    "unsupported image format":"The image format is not supported. Try a different image.",
    "image_url is not supported":"This provider doesn't support image input. Try a different model or remove the image.",
    "401":"Authentication failed. Check your API key.",
    "402":"Payment required. Check your account billing.",
    }
    for key ,msg in friendly .items ():
        if key .lower ()in error_text .lower ():
            return msg 
    return error_text 


def _animation_dir (char_id :str )->str :
    """Return the filesystem path to a character's animation directory, checking data/ then repo."""
    data_dir =CHARACTERS_DIR /char_id /"anim"
    if data_dir .exists ():
        return str (data_dir )
    repo_dir =PROJECT_ROOT /"backend"/"characters"/char_id /"anim"
    if repo_dir .exists ():
        return str (repo_dir )
    return str (data_dir )

def _resolve_animation (text :str ,char_id :str )->str |None :
    """Resolve an animation URL from roleplay/action text by keyword matching."""
    import os 
    words =text .lower ().split ()
    char_dir =_animation_dir (char_id )
    default_dir =_animation_dir ("default")
    candidates =[]
    if os .path .exists (default_dir ):
        candidates .extend (os .listdir (default_dir ))
    if char_id and char_id !="default"and os .path .exists (char_dir ):
        candidates .extend (os .listdir (char_dir ))
    for word in words :
        for f in candidates :
            if f .endswith (".vrma"):
                name =f .replace (".vrma","").lower ()
                if word ==name or name .startswith (word )or word in name :
                    is_char =char_id and char_id !="default"and os .path .exists (os .path .join (char_dir ,f ))
                    base =char_id if is_char else "default"
                    return f"/characters/{base }/anim/{f }"
    return None 


async def handle_chat (websocket :WebSocket ):
    await websocket .accept ()
    logger .warning ("Chat WebSocket connected")


    current_stream_idx =0 
    pending_tasks :set [asyncio .Task ]=set ()
    voice_output_enabled =False 
    voice_pipeline =None 
    voice_task =None 

    def _track_task (t :asyncio .Task ):
        pending_tasks .add (t )
        t .add_done_callback (pending_tasks .discard )

    async def _send_json (data :dict ):
        """Send JSON, raising WebSocketDisconnect and breaking on any failure."""
        try :
            await websocket .send_json (data )
        except WebSocketDisconnect :
            raise 
        except Exception :
            logger .warning ("send_json failed — connection likely dead")
            raise 

    try :
        await _send_json ({
        "type":"session",
        "id":memory ().get_current_session ()
        })
    except Exception :
        pass 

    try :
        while True :
            data =await websocket .receive_json ()
            msg_type =data .get ("type")

            if msg_type =="command":
                cmd =data .get ("command","")
                if cmd in ("voice_output_on","voice_on"):
                    voice_output_enabled =True 
                    logger .debug ("Voice output enabled by client")
                    await _send_json ({"type":"voice_state","state":"idle"})
                elif cmd in ("voice_output_off","voice_off"):
                    voice_output_enabled =False 
                    logger .debug ("Voice output disabled by client")
                    await _send_json ({"type":"voice_state","state":"idle"})
                elif cmd =="voice_input_on":
                    stt_engine =settings ().get ("voice.stt_engine","faster-whisper")
                    if stt_engine =="browser":
                        await _send_json ({"type":"voice_state","state":"recording"})
                        logger .debug ("Voice input started (browser STT)")
                    else :
                        if voice_pipeline is None :
                            _main_loop =asyncio .get_running_loop ()

                            def on_transcription (text ):
                                try :
                                    asyncio .run_coroutine_threadsafe (
                                    _send_json ({"type":"user_message_from_voice","text":text }),
                                    _main_loop 
                                    )
                                except Exception as e :
                                    logger .error (f"Voice transcription send failed: {e }")

                            voice_cfg =settings ()
                            voice_pipeline =VoicePipeline (
                            agent_callback =on_transcription ,
                            stt_engine =stt_engine ,
                            settings =voice_cfg ,
                            )
                            if stt_engine =="openai-whisper":
                                whisper_key =voice_cfg .get ("voice.openai_whisper.api_key","")
                                if whisper_key :
                                    whisper_model =voice_cfg .get ("voice.openai_whisper.model","whisper-1")
                                    voice_pipeline .configure_openai_stt (whisper_key ,whisper_model )
                            elif stt_engine =="groq-whisper":
                                groq_key =voice_cfg .get ("voice.groq_whisper.api_key","")
                                if groq_key :
                                    groq_model =voice_cfg .get ("voice.groq_whisper.model","whisper-large-v3")
                                    groq_url =voice_cfg .get ("voice.groq_whisper.base_url",None )
                                    voice_pipeline .configure_groq_stt (groq_key ,groq_model ,groq_url )
                            elif stt_engine =="whispercpp":
                                wcpp_url =voice_cfg .get ("voice.whispercpp.url",None )
                                voice_pipeline .configure_whispercpp_stt (wcpp_url )
                            elif stt_engine =="deepgram":
                                dg_key =voice_cfg .get ("voice.deepgram.api_key","")
                                if dg_key :
                                    dg_model =voice_cfg .get ("voice.deepgram.model","nova-2")
                                    voice_pipeline .configure_deepgram_stt (dg_key ,dg_model )
                        if voice_task is None or voice_task .done ():
                            if voice_task and voice_task .exception ():
                                logger .error (f"Previous voice task failed: {voice_task .exception ()}")
                            loop =asyncio .get_running_loop ()
                            voice_task =loop .run_in_executor (None ,voice_pipeline .listen_loop )
                        await _send_json ({"type":"voice_state","state":"recording"})
                        logger .debug ("Voice input started")
                elif cmd =="voice_input_off":
                    stt_engine =settings ().get ("voice.stt_engine","faster-whisper")
                    if stt_engine =="browser":
                        await _send_json ({"type":"voice_state","state":"idle"})
                        logger .debug ("Voice input stopped (browser STT)")
                    else :
                        if voice_pipeline :
                            voice_pipeline .stop_listening ()
                        if voice_task and not voice_task .done ():
                            voice_task .cancel ()
                            voice_task =None 
                        voice_pipeline =None 
                        await _send_json ({"type":"voice_state","state":"idle"})
                        logger .debug ("Voice input stopped")
                elif cmd =="speak":
                    speak_text =data .get ("text","").strip ()
                    if speak_text :
                        logger .debug (f"Speak command: {speak_text [:50 ]}")
                        t =asyncio .create_task (synthesize_now (speak_text ,websocket ))
                        _track_task (t )
                continue 

            if msg_type =="slash_command":
                cmd =data .get ("command","").lower ()
                args =data .get ("args","")
                if cmd =="clear":
                    await memory ().clear ()
                    sid =memory ().start_session ()
                    relationship ()._cache .clear ()
                    await _send_json ({
                    "type":"chat_append","role":"system",
                    "text":"Memory cleared.","finished":True ,"session_id":sid 
                    })
                elif cmd =="new":
                    sid =memory ().start_session ()
                    await _send_json ({
                    "type":"chat_append","role":"system",
                    "text":f"New session started: {sid }","finished":True ,"session_id":sid 
                    })
                elif cmd =="help":
                    help_text =(
                    "Slash commands:\n"
                    "/clear — clear history\n"
                    "/new — start new session\n"
                    "/provider <name> — switch provider\n"
                    "/model <name> — switch model\n"
                    "/session <id> — show/load session\n"
                    "/status — show current provider, model, session\n"
                    "/compact — force memory compaction\n"
                    "/help — show this"
                    )
                    await _send_json (
                    {"type":"chat_append","role":"system","text":help_text ,"finished":True })
                elif cmd =="provider":
                    if args :
                        loop =asyncio .get_running_loop ()
                        s =settings ()
                        await loop .run_in_executor (None ,lambda :s .set ("provider.active",args ))
                        await _send_json (
                        {"type":"chat_append","role":"system","text":f"Switched to provider: {args }","finished":True })
                    else :
                        await _send_json (
                        {"type":"chat_append","role":"system","text":f"Current provider: {settings ().get ('provider.active','gemini')}","finished":True })
                elif cmd =="model":
                    if args :
                        provider =settings ().get ("provider.active","gemini")
                        loop =asyncio .get_running_loop ()
                        s =settings ()
                        await loop .run_in_executor (None ,lambda :s .set (f"provider.{provider }.model",args ))
                        await _send_json (
                        {"type":"chat_append","role":"system","text":f"Switched model to: {args }","finished":True })
                    else :
                        provider =settings ().get ("provider.active","gemini")
                        model =settings ().get (f"provider.{provider }.model","not set")
                        await _send_json (
                        {"type":"chat_append","role":"system","text":f"Current model ({provider }): {model }","finished":True })
                elif cmd =="session":
                    if args :
                        await _send_json (
                        {"type":"chat_append","role":"system","text":f"Load session by navigating to #chat/{args }","finished":True })
                    else :
                        sid =memory ().get_current_session ()
                        await _send_json (
                        {"type":"chat_append","role":"system","text":f"Current session: {sid }","finished":True })
                elif cmd =="compact":
                    await _send_json (
                    {"type":"chat_append","role":"system","text":"Compacting memory...","finished":True })
                    try :
                        await memory ().check_and_summarize ()
                        await _send_json (
                        {"type":"chat_append","role":"system","text":"Memory compacted.","finished":True })
                    except Exception as e :
                        await _send_json (
                        {"type":"chat_append","role":"system","text":f"Compaction failed: {e }","finished":True })
                elif cmd =="status":
                    s =settings ()
                    active =s .get ("provider.active","?")
                    model =s .get (f"provider.{active }.model","?")
                    sid =memory ().get_current_session ()
                    await _send_json (
                    {"type":"chat_append","role":"system","text":f"Provider: {active }\nModel: {model }\nSession: {sid }","finished":True })
                else :
                    await _send_json (
                    {"type":"chat_append","role":"system","text":f"Unknown command: /{cmd }. Try /help","finished":True })
                continue 

            if msg_type =="idle_prompt_request":
                try :
                    text =await agent ().generate_idle_prompt ()
                    if text :
                        await _send_json ({"type":"idle_prompt","text":text })

                    asyncio .create_task (agent ().subconscious_reflect ())
                except Exception as e :
                    logger .warning (f"Idle prompt request failed: {e }")
                continue 

            if msg_type =="user_message":
                text =data .get ("text","").strip ()
                images =data .get ("images",None )
                if not text and not images :
                    continue 

                current_stream_idx +=1 
                this_stream =current_stream_idx 

                await _send_json ({"type":"chat_start","role":"assistant"})
                await _send_json ({"type":"emotion","emotion":"neutral"})
                await _send_json ({"type":"expression","expression":"neutral"})

                tts_tasks =[]

                try :
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

                    char_id =settings ().get ("character.active","default")
                    rel_context =relationship ().get_context_string (char_id )
                    logger .debug (f"ws:user_message - calling agent.handle_user_input for char_id={char_id }, text={text [:50 ]}")

                    item_count =0 
                    had_error =False 
                    async for item in agent ().handle_user_input (text ,images =images ,relationship_context =rel_context ):
                        item_count +=1 
                        logger .debug (f"ws:item received #{item_count }: {type (item ).__name__ } = {item [:50 ]if isinstance (item ,str )else item }")
                        if isinstance (item ,tuple )and item [0 ]=='__emotion__':
                            current_emotion =item [1 ]
                            await _send_json ({"type":"emotion","emotion":current_emotion })
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__expression__':
                            await _send_json ({"type":"expression","expression":item [1 ]})
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__thinking__':
                            await _send_json ({"type":"thinking","text":item [1 ]})
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__animation__':
                            anim_name =item [1 ]
                            await _send_json ({"type":"animation","name":anim_name ,"url":f"/characters/{char_id }/anim/{anim_name }.vrma"})
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__avatar__':
                            try :
                                av =json .loads (item [1 ])
                                av_type =av .get ("type")if isinstance (av ,dict )else None 
                                if av_type =="emotion":
                                    current_emotion =av .get ("emotion","neutral")
                                    await _send_json ({"type":"emotion","emotion":current_emotion })
                                elif av_type =="expression":
                                    await _send_json ({"type":"expression","expression":av .get ("expression","neutral")})
                                elif av_type =="roleplay":
                                    action =av .get ("action","")
                                    rp_text =f"*{action }* "
                                    full_response +=rp_text 
                                    sentence_buffer +=rp_text 
                                    anim_url =_resolve_animation (action ,char_id )
                                    await _send_json ({"type":"roleplay","text":action ,"animation_url":anim_url })
                            except Exception :
                                pass 
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__tool__':
                            await _send_json ({"type":"tool_call","text":item [1 ]})
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__error__':
                            had_error =True 
                            await _send_json ({
                            "type":"chat_append","role":"assistant",
                            "text":_normalize_error (str (item [1 ])),"finished":True ,"error":True 
                            })
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__permission__':
                            await _send_json ({"type":"permission_request","command":item [1 ]})
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__roleplay__':
                            rp_text =f"*{item [1 ]}* "
                            full_response +=rp_text 
                            sentence_buffer +=rp_text 

                            anim_url =_resolve_animation (item [1 ],char_id )
                            await _send_json ({"type":"roleplay","text":item [1 ],"animation_url":anim_url })
                            continue 

                        token =item 
                        full_response +=token 
                        sentence_buffer +=token 
                        await _send_json ({
                        "type":"chat_append","role":"assistant","text":token ,"finished":False 
                        })

                        if voice_output_enabled and re .search (r'[.!?。！？]\s|[.!?。！？]$|,\s{10,}',sentence_buffer ):
                            parts =re .split (r'(?<=[.!?。！？])\s',sentence_buffer )
                            if len (parts )>1 :
                                complete =parts [0 ].strip ()
                                sentence_buffer =' '.join (parts [1 :])
                                if complete :
                                    await _send_json ({"type":"voice_state","state":"speaking"})
                                    t =asyncio .create_task (synthesize_sentence (
                                    complete ,sentence_idx ,this_stream ,current_stream_idx ,
                                    websocket ,current_emotion ))
                                    _track_task (t )
                                    tts_tasks .append (t )
                                    sentence_idx +=1 

                    if full_response .strip ():
                        try :
                            relationship ().analyze_message ("user",text ,char_id )
                            relationship ().analyze_message ("assistant",full_response ,char_id )
                        except Exception as e :
                            logger .warning (f"Relationship tracking error: {e }")

                    await _send_json ({"type":"viseme","value":0.0 })

                    if voice_output_enabled and sentence_buffer .strip ():
                        await _send_json ({"type":"voice_state","state":"speaking"})
                        t =asyncio .create_task (synthesize_sentence (
                        sentence_buffer .strip (),sentence_idx ,this_stream ,
                        current_stream_idx ,websocket ,current_emotion ))
                        _track_task (t )
                        tts_tasks .append (t )
                        sentence_idx +=1 

                    if tts_tasks :
                        await asyncio .gather (*tts_tasks ,return_exceptions =True )
                        await _send_json ({"type":"voice_state","state":"idle"})

                except (WebSocketDisconnect ,asyncio .CancelledError ):
                    raise 
                except Exception as e :
                    logger .error (f"Agent error: {e }, item_count={item_count if 'item_count'in locals ()else 'unknown'}")
                    for t in tts_tasks :
                        if not t .done ():
                            t .cancel ()
                    error_text =_normalize_error (str (e ))
                    await _send_json ({
                    "type":"chat_append","role":"assistant",
                    "text":f"Error: {error_text }","finished":True ,"error":True 
                    })
                else :
                    if not had_error :
                        await _send_json ({"type":"emotion","emotion":"neutral"})
                        await _send_json ({"type":"expression","expression":"neutral"})
                        await _send_json ({
                        "type":"chat_append","role":"assistant","text":"","finished":True 
                        })

    except WebSocketDisconnect :
        logger .warning ("Chat WebSocket disconnected")
    except Exception as e :
        logger .error (f"WebSocket error: {e }")
    finally :
        for t in pending_tasks :
            if not t .done ():
                t .cancel ()
        if voice_pipeline :
            voice_pipeline .stop_listening ()
        if voice_task and not voice_task .done ():
            voice_task .cancel ()
