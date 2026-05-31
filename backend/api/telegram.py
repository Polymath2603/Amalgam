"""
Telegram bot interface for Amalgam.
Provides a remote chat interface with support for text and voice messages.
"""
import os 
import asyncio 
import logging 
import json 
import io 
from typing import Optional 

from telegram import Update ,Bot 
from telegram .ext import ApplicationBuilder ,CommandHandler ,MessageHandler ,ContextTypes ,filters 
from telegram .constants import ParseMode 

from backend .core .startup import init_application ,shutdown_application 
from backend .core .deps import get_shared 

logger =logging .getLogger (__name__ )

class TelegramBot :
    def __init__ (self ):
        self .shared =get_shared ()
        self .settings =self .shared ["settings"]
        self .agent =self .shared ["agent"]
        self .memory =self .shared ["memory"]
        self .tts =self .shared ["tts"]

        self .token =self .settings .get ("telegram.token")
        self .allowed_users =self .settings .get ("telegram.allowed_users",[])
        self .application =None 

    def _is_allowed (self ,update :Update )->bool :
        if not self .allowed_users :
            return True 
        user =update .effective_user 
        return str (user .id )in [str (u )for u in self .allowed_users ]or user .username in [str (u )for u in self .allowed_users ]

    async def start (self ,update :Update ,context :ContextTypes .DEFAULT_TYPE ):
        if not self ._is_allowed (update ):
            await update .message .reply_text ("Unauthorized.")
            return 

        session_id =self .memory .start_session ()
        await update .message .reply_text (
        f"<b>Amalgam</b> active.\nSession: <code>{session_id [:12 ]}</code>",
        parse_mode =ParseMode .HTML 
        )

    async def new_session (self ,update :Update ,context :ContextTypes .DEFAULT_TYPE ):
        if not self ._is_allowed (update ):return 
        sid =self .memory .start_session ()
        await update .message .reply_text (f"New session started: <code>{sid [:12 ]}</code>",parse_mode =ParseMode .HTML )

    async def clear_memory (self ,update :Update ,context :ContextTypes .DEFAULT_TYPE ):
        if not self ._is_allowed (update ):return 
        await self .memory .clear ()
        sid =self .memory .start_session ()
        await update .message .reply_text ("Memory cleared and new session started.")

    async def handle_message (self ,update :Update ,context :ContextTypes .DEFAULT_TYPE ):
        if not self ._is_allowed (update ):return 

        text =update .message .text 
        if not text :return 

        await context .bot .send_chat_action (chat_id =update .effective_chat .id ,action ="typing")

        response_msg =await update .message .reply_text ("...")
        full_text =""
        last_update_time =asyncio .get_event_loop ().time ()

        try :
            async for chunk in self .agent .handle_user_input (text ):
                if isinstance (chunk ,tuple ):


                    continue 

                full_text +=chunk 

                now =asyncio .get_event_loop ().time ()
                if now -last_update_time >1.5 :
                    try :
                        await context .bot .edit_message_text (
                        chat_id =update .effective_chat .id ,
                        message_id =response_msg .message_id ,
                        text =full_text +" ▌"
                        )
                        last_update_time =now 
                    except Exception :
                        pass 

            if full_text :
                await context .bot .edit_message_text (
                chat_id =update .effective_chat .id ,
                message_id =response_msg .message_id ,
                text =full_text ,
                parse_mode =ParseMode .MARKDOWN 
                )
            else :
                await context .bot .edit_message_text (
                chat_id =update .effective_chat .id ,
                message_id =response_msg .message_id ,
                text ="[Empty response]"
                )
        except Exception as e :
            logger .error (f"Telegram agent error: {e }")
            await update .message .reply_text (f"Error: {e }")

    async def handle_voice (self ,update :Update ,context :ContextTypes .DEFAULT_TYPE ):
        if not self ._is_allowed (update ):return 

        voice =update .message .voice 
        file =await context .bot .get_file (voice .file_id )




        await update .message .reply_text ("Voice messages are not yet fully implemented in Telegram mode (requires OGG->WAV conversion).")

    async def run (self ):
        if not self .token :
            print ("Error: Telegram token not found in settings. Set 'telegram.token' in data/settings.json")
            return 

        await init_application ()

        self .application =ApplicationBuilder ().token (self .token ).build ()

        self .application .add_handler (CommandHandler ("start",self .start ))
        self .application .add_handler (CommandHandler ("new",self .new_session ))
        self .application .add_handler (CommandHandler ("clear",self .clear_memory ))
        self .application .add_handler (MessageHandler (filters .TEXT &(~filters .COMMAND ),self .handle_message ))
        self .application .add_handler (MessageHandler (filters .VOICE ,self .handle_voice ))

        print (f"Telegram bot starting...")
        async with self .application :
            await self .application .initialize ()
            await self .application .start ()
            await self .application .updater .start_polling ()

            stop_event =asyncio .Event ()
            try :
                await stop_event .wait ()
            except (KeyboardInterrupt ,asyncio .CancelledError ):
                pass 
            finally :
                await self .application .updater .stop ()
                await self .application .stop ()
                await self .application .shutdown ()
                await shutdown_application ()

async def run_telegram ():
    bot =TelegramBot ()
    await bot .run ()
