"""AllTalk/XTTS provider — local TTS via AllTalk API."""
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider, decode_wav, retry_http 

logger =logging .getLogger (__name__ )


class AllTalkProvider (TTSProvider ):
    def __init__ (self ,voice ="female_01.wav"):
        super ().__init__ (voice )
        self ._url ="http://127.0.0.1:7851"
        self ._api_key =""
        self ._language ="en"
        self ._version ="v2"
        self ._rvc_voice =""
        self ._rvc_pitch ="0"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def configure (self ,url :str =None ,language :str ="en",version :str ="v2",
    rvc_voice :str ="",rvc_pitch :str ="0"):
        if url :
            self ._url =url .rstrip ("/").replace ("/api/tts-generate","")
        self ._language =language 
        self ._version =version 
        self ._rvc_voice =rvc_voice 
        self ._rvc_pitch =rvc_pitch 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        base_url =self ._url .rstrip ("/")
        params ={
        "text_input":text ,
        "text_filtering":"standard",
        "character_voice_gen":self .voice ,
        "narrator_enabled":"false",
        "narrator_voice_gen":self .voice ,
        "text_not_inside":"character",
        "language":self ._language ,
        "output_file_name":"opencode_output",
        "output_file_timestamp":"true",
        "autoplay":"false",
        "autoplay_volume":"0.8",
        }
        if self ._version =="v2"and self ._rvc_voice and self ._rvc_voice !="Disabled":
            params ["rvccharacter_voice_gen"]=self ._rvc_voice 
            params ["rvccharacter_pitch"]=self ._rvc_pitch 

        try :
            response =await retry_http (self ._client ,"POST",f"{base_url }/api/tts-generate",
            data =params ,
            headers ={"Content-Type":"application/x-www-form-urlencoded"},
            )
            if response is None or response .status_code !=200 :
                logger .error ("AllTalk TTS error or request failed")
                return np .zeros (0 ,dtype =np .float32 ),None ,24000 

            data =response .json ()
            audio_url =data .get ("output_file_url","")
            if not audio_url :
                logger .error ("AllTalk: no output_file_url in response")
                return np .zeros (0 ,dtype =np .float32 ),None ,24000 

            if self ._version =="v2":
                audio_url =f"{base_url }{audio_url }"

            audio_resp =await retry_http (self ._client ,"GET",audio_url )
            if audio_resp is None or audio_resp .status_code !=200 :
                logger .error (f"AllTalk: failed to fetch audio from {audio_url }")
                return np .zeros (0 ,dtype =np .float32 ),None ,24000 

            audio_np ,sr =decode_wav (audio_resp .content )
            return audio_np ,None ,sr 
        except httpx .HTTPStatusError as e :
            logger .error (f"AllTalk TTS HTTP error: {e }")

        except httpx .RequestError as e :
            logger .error (f"AllTalk TTS request error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 
        except Exception as e :
            logger .error (f"AllTalk TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

    async def close (self ):
        await self ._client .aclose ()
