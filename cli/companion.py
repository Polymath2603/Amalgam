import asyncio 
import json 
import os 
import sys 
import time 
import threading 
import logging 
import re 
from typing import Optional 

import websockets 
from rich .console import Console 
from rich .panel import Panel 
from rich .live import Live 
from rich .text import Text 
from rich .markdown import Markdown 

from cli import _make_console ,_show_banner 

logger =logging .getLogger (__name__ )

class CompanionState :
    SLEEPING ="sleeping"
    ACTIVE ="active"

class CompanionMode :
    def __init__ (self ):
        self .console =_make_console ()
        self .state =CompanionState .SLEEPING 
        self .ws :Optional [websockets .WebSocketClientProtocol ]=None 
        self .last_interaction_time =time .time ()
        self .timeout_duration =46.0 
        self .session_id =None 
        self .base_url ="ws://localhost:8000/ws/chat"
        self ._stop_event =asyncio .Event ()
        self .current_response =""
        self .is_thinking =False 

    async def connect (self ):
        while not self ._stop_event .is_set ():
            try :
                self .ws =await websockets .connect (self .base_url )
                logger .info ("Connected to backend WebSocket")
                break 
            except Exception as e :
                logger .debug (f"Waiting for backend... ({e })")
                await asyncio .sleep (1 )

    async def _send (self ,data :dict ):
        if self .ws :
            await self .ws .send (json .dumps (data ))

    async def wake_up (self ,reason ="wake_word"):
        if self .state ==CompanionState .SLEEPING :
            self .state =CompanionState .ACTIVE 
            self .console .print (f"[bold yellow]\[System][/bold yellow] Waking up... ({reason })")
            await self ._send ({"type":"command","command":"voice_input_on"})
            await self ._send ({"type":"command","command":"voice_output_on"})
            await self ._send ({"type":"command","command":"avatar_set_visibility","visible":True })
        self .last_interaction_time =time .time ()

    async def sleep (self ):
        if self .state ==CompanionState .ACTIVE :
            self .state =CompanionState .SLEEPING 
            self .console .print ("[bold blue]\[System][/bold blue] Going to sleep...")
            await self ._send ({"type":"command","command":"voice_input_off"})
            await self ._send ({"type":"command","command":"avatar_set_visibility","visible":False })

    async def handle_backend_messages (self ):
        try :
            async for message in self .ws :
                data =json .loads (message )
                msg_type =data .get ("type")

                if msg_type =="session":
                    self .session_id =data .get ("id")
                    await self ._send ({"type":"command","command":"avatar_set_visibility","visible":False })
                    await self ._send ({"type":"command","command":"wake_word_on"})

                elif msg_type =="wake_word_detected":
                    await self .wake_up (reason =f"wake word: {data .get ('word')}")

                elif msg_type =="user_message_from_voice":
                    self .console .print (f"[bold cyan]You (voice):[/bold cyan] {data .get ('text')}")
                    self .last_interaction_time =time .time ()

                elif msg_type =="chat_start":
                    self .current_response =""
                    self .is_thinking =False 
                    self .last_interaction_time =time .time ()
                    self ._live =Live (Text (""),console =self .console ,refresh_per_second =10 )
                    self ._live .start ()

                elif msg_type =="chat_append":
                    text =data .get ("text","")
                    self .current_response +=text 
                    if hasattr (self ,'_live')and self ._live :
                        self ._live .update (Panel (Markdown (self .current_response ),title ="Assistant",border_style ="green"))

                    if data .get ("finished"):
                        if hasattr (self ,'_live')and self ._live :
                            self ._live .stop ()
                            self ._live =None 
                        self .console .print (Panel (Markdown (self .current_response ),title ="Assistant",border_style ="green"))
                        self .last_interaction_time =time .time ()

                elif msg_type =="thinking":
                    if not self .is_thinking :
                        self .console .print ("[dim]thinking...[/dim]")
                        self .is_thinking =True 

                elif msg_type =="visibility":
                    visible =data .get ("visible")
                    if visible :
                        await self .wake_up (reason ="AI request")
                    else :
                        await self ._send ({"type":"command","command":"avatar_set_visibility","visible":False })

        except Exception as e :
            logger .error (f"Error in backend message handler: {e }")

    async def input_loop (self ):
        loop =asyncio .get_running_loop ()
        while not self ._stop_event .is_set ():
            try :
                text =await loop .run_in_executor (None ,lambda :sys .stdin .readline ().strip ())
                if not text :
                    continue 

                if text .startswith ("/"):
                    if text =="/exit":
                        self ._stop_event .set ()
                        break 
                    elif text =="/sleep":
                        await self .sleep ()
                    elif text =="/wake":
                        await self .wake_up (reason ="manual command")
                    elif text =="/overlay":

                        if self .state ==CompanionState .ACTIVE :
                            await self ._send ({"type":"command","command":"avatar_set_visibility","visible":True })
                        else :
                            await self .wake_up (reason ="overlay toggle")
                    continue 

                await self .wake_up (reason ="terminal input")
                await self ._send ({"type":"user_message","text":text })

            except Exception as e :
                logger .error (f"Input loop error: {e }")

    async def timeout_monitor (self ):
        while not self ._stop_event .is_set ():
            await asyncio .sleep (1 )
            if self .state ==CompanionState .ACTIVE :
                elapsed =time .time ()-self .last_interaction_time 
                if elapsed >=self .timeout_duration :
                    await self .sleep ()

    async def run (self ):
        self .console .print ("[bold yellow]Amalgam Companion Mode[/bold yellow]")
        self .console .print ("[dim]Terminal-based chat with background voice loop and avatar overlay.[/dim]")
        self .console .print ("[dim]Wait for 46s of silence to sleep, or use /exit to quit.[/dim]\n")

        await self .connect ()

        await asyncio .gather (
        self .handle_backend_messages (),
        self .input_loop (),
        self .timeout_monitor ()
        )

async def run_companion ():
    companion =CompanionMode ()
    await companion .run ()

if __name__ =="__main__":
    asyncio .run (run_companion ())
