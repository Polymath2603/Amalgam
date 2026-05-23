"""
WebSocket chat handler — extracted from server.py.
"""
import asyncio 
import json 
import re 
import logging 

from fastapi import WebSocket ,WebSocketDisconnect 
from backend .api .deps import settings ,memory ,tts ,agent ,relationship 
from backend .api .ws .tts_service import synthesize_sentence ,synthesize_now ,increment_stream_idx ,set_stream_idx 
from backend .voice .pipeline import VoicePipeline 

logger =logging .getLogger (__name__ )


async def handle_chat (websocket :WebSocket ):
    await websocket .accept ()
    logger .warning ("Chat WebSocket connected")


    try :
        await websocket .send_json ({
        "type":"session",
        "id":memory ().get_current_session ()
        })
    except Exception :
        pass 

    voice_output_enabled =False 
    voice_pipeline =None 
    voice_task =None 
    set_stream_idx (0 )

    try :
        while True :
            data =await websocket .receive_json ()
            msg_type =data .get ("type")

            if msg_type =="command":
                cmd =data .get ("command","")
                if cmd in ("voice_output_on","voice_on"):
                    voice_output_enabled =True 
                    logger .debug ("Voice output enabled by client")
                    await websocket .send_json ({"type":"voice_state","state":"idle"})
                elif cmd in ("voice_output_off","voice_off"):
                    voice_output_enabled =False 
                    logger .debug ("Voice output disabled by client")
                    await websocket .send_json ({"type":"voice_state","state":"idle"})
                elif cmd =="voice_input_on":
                    stt_engine =settings ().get ("voice.stt_engine","faster-whisper")
                    if stt_engine =="browser":
                        await websocket .send_json ({"type":"voice_state","state":"recording"})
                        logger .debug ("Voice input started (browser STT)")
                    else :
                        if voice_pipeline is None :
                            _main_loop =asyncio .get_running_loop ()
                            def on_transcription (text ):
                                try :
                                    asyncio .run_coroutine_threadsafe (
                                    websocket .send_json ({"type":"user_message_from_voice","text":text }),
                                    _main_loop 
                                    )
                                except Exception as e :
                                    logger .error (f"Voice transcription send failed: {e }")
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
                        logger .debug ("Voice input started")
                elif cmd =="voice_input_off":
                    stt_engine =settings ().get ("voice.stt_engine","faster-whisper")
                    if stt_engine =="browser":
                        await websocket .send_json ({"type":"voice_state","state":"idle"})
                        logger .debug ("Voice input stopped (browser STT)")
                    else :
                        if voice_pipeline :
                            voice_pipeline .stop_listening ()
                        if voice_task and not voice_task .done ():
                            voice_task .cancel ()
                            voice_task =None 
                        voice_pipeline =None 
                        await websocket .send_json ({"type":"voice_state","state":"idle"})
                        logger .debug ("Voice input stopped")
                elif cmd =="speak":
                    speak_text =data .get ("text","").strip ()
                    if speak_text :
                        logger .debug (f"Speak command: {speak_text [:50 ]}")
                        asyncio .create_task (synthesize_now (speak_text ,websocket ))
                continue 

            if msg_type =="user_message":
                text =data .get ("text","").strip ()
                images =data .get ("images",None )
                if not text and not images :
                    continue 

                if text =="/clear":
                    await memory ().clear ()
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

                current_stream =increment_stream_idx ()
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
                    async for item in agent ().handle_user_input (text ,images =images ,relationship_context =rel_context ):
                        item_count +=1 
                        logger .debug (f"ws:item received #{item_count }: {type (item ).__name__ } = {item [:50 ]if isinstance (item ,str )else item }")
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
                        if isinstance (item ,tuple )and item [0 ]=='__animation__':
                            anim_name =item [1 ]
                            try :
                                anim_url =f"/characters/{char_id }/anim/{anim_name }.vrma"
                                await websocket .send_json ({"type":"animation","name":anim_name ,"url":anim_url })
                            except WebSocketDisconnect :
                                raise 
                            except Exception :
                                pass 
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__tool__':
                            try :
                                await websocket .send_json ({"type":"tool_call","text":item [1 ]})
                            except WebSocketDisconnect :
                                raise 
                            except Exception :
                                pass 
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__error__':
                            try :
                                await websocket .send_json ({
                                "type":"chat_append","role":"assistant",
                                "text":str (item [1 ]),"finished":True ,"error":True 
                                })
                            except WebSocketDisconnect :
                                raise 
                            except Exception :
                                pass 
                            continue 
                        if isinstance (item ,tuple )and item [0 ]=='__permission__':
                            try :
                                await websocket .send_json ({"type":"permission_request","command":item [1 ]})
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
                            "type":"chat_append","role":"assistant","text":token ,"finished":False 
                            })
                        except WebSocketDisconnect :
                            raise 
                        except Exception :
                            pass 

                        if voice_output_enabled and re .search (r'[.!?。！？]\s|[.!?。！？]$|,\s{10,}',sentence_buffer ):
                            parts =re .split (r'(?<=[.!?。！？])\s',sentence_buffer )
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
                                    task =asyncio .create_task (synthesize_sentence (complete ,sentence_idx ,current_stream ,websocket ,current_emotion ))
                                    tts_tasks .append (task )
                                    sentence_idx +=1 


                    if full_response .strip ():
                        try :
                            relationship ().analyze_message ("user",text ,char_id )
                            relationship ().analyze_message ("assistant",full_response ,char_id )
                            asyncio .create_task (memory ().extract_facts (text ,full_response .strip ()))
                        except Exception as e :
                            logger .warning (f"Relationship/fact tracking error: {e }")

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
                        task =asyncio .create_task (synthesize_sentence (sentence_buffer .strip (),sentence_idx ,current_stream ,websocket ,current_emotion ))
                        tts_tasks .append (task )
                        sentence_idx +=1 

                    if tts_tasks :
                        await asyncio .gather (*tts_tasks ,return_exceptions =True )
                        try :
                            await websocket .send_json ({"type":"voice_state","state":"idle"})
                        except Exception :
                            pass 

                except Exception as e :
                    logger .error (f"Agent error: {e }, item_count={item_count if 'item_count'in locals ()else 'unknown'}")
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
                        if error_text .startswith ('{'):
                            err_obj =json .loads (error_text )
                            error_text =err_obj .get ('message',error_text )
                    except Exception :
                        pass 
                    await websocket .send_json ({
                    "type":"chat_append","role":"assistant",
                    "text":f"Error: {error_text }","finished":True ,"error":True 
                    })
                else :
                    try :
                        await websocket .send_json ({"type":"emotion","emotion":"neutral"})
                        await websocket .send_json ({"type":"expression","expression":"neutral"})
                        await websocket .send_json ({
                        "type":"chat_append","role":"assistant","text":"","finished":True 
                        })
                    except WebSocketDisconnect :
                        raise 
                    except Exception :
                        pass 

    except WebSocketDisconnect :
        logger .warning ("Chat WebSocket disconnected")
    except Exception as e :
        logger .error (f"WebSocket error: {e }")
    finally :
        if voice_pipeline :
            voice_pipeline .stop_listening ()
        if voice_task and not voice_task .done ():
            voice_task .cancel ()
