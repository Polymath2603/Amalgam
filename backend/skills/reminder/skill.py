import asyncio 
import logging 
from typing import Any 

from backend .skills .base import Skill 

logger =logging .getLogger (__name__ )

_active_timers :dict [str ,asyncio .Task ]={}


def _clean_timer (timer_id :str ):
    _active_timers .pop (timer_id ,None )


class ReminderSkill (Skill ):
    name ="reminder"
    description ="Set a timer or reminder that fires after a delay"
    parameters ={
    "type":"object",
    "properties":{
    "text":{"type":"string","description":"The reminder message"},
    "delay_seconds":{"type":"integer","description":"Seconds to wait before firing","default":60 },
    },
    "required":["text"],
    }

    async def execute (self ,args :dict [str ,Any ])->str :
        text =args .get ("text","")
        delay =int (args .get ("delay_seconds",60 ))
        if not text :
            return "Error: text is required"

        timer_id =f"reminder_{id (text )}_{delay }"
        if timer_id in _active_timers :
            return f"Timer already exists for this reminder"

        async def _fire ():
            try :
                await asyncio .sleep (delay )
                logger .info (f"REMINDER: {text }")
            except asyncio .CancelledError :
                pass 
            finally :
                _clean_timer (timer_id )

        task =asyncio .create_task (_fire ())
        _active_timers [timer_id ]=task 

        if delay <60 :
            display =f"{delay }s"
        elif delay <3600 :
            display =f"{delay //60 }m {delay %60 }s"
        else :
            display =f"{delay //3600 }h {(delay %3600 )//60 }m"

        return f"Reminder set: \"{text }\" will fire in {display }"
