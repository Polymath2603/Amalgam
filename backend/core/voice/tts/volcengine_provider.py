"""Volcengine TTS provider — ByteDance."""
import json 
import logging 
import base64 
import uuid 
from urllib .parse import urlencode 

import numpy as np 
import httpx 

from .base import TTSProvider, retry_http 

logger =logging .getLogger (__name__ )


class VolcengineProvider (TTSProvider ):
    def __init__ (self ,voice ="BV001_streaming"):
        super ().__init__ (voice )
        self ._app_id =""
        self ._access_token =""
        self ._cluster ="volcano_tts"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,app_id :str ,access_token :str ,cluster :str ="volcano_tts"):
        self ._app_id =app_id 
        self ._access_token =access_token 
        self ._cluster =cluster 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ()or not self ._access_token :
            if not self ._access_token :
                logger .warning ("Volcengine access token not configured")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

        url ="https://openspeech.bytedance.com/api/v1/tts"
        headers ={
        "Content-Type":"application/json",
        "Authorization":f"Bearer;{self ._access_token }",
        }
        body ={
        "app":{"appid":self ._app_id ,"cluster":self ._cluster },
        "user":{"uid":"amalgam"},
        "request":{
        "reqid":str (uuid .uuid4 ()),
        "text":text ,
        "text_type":"plain",
        "operation":"query",
        "voice_type":self .voice ,
        "audio_config":{
        "audio_type":"wav",
        "sample_rate":24000 ,
        },
        },
        }

        try :
            response =await retry_http (self ._client ,"POST",url ,json =body ,headers =headers )
            if response is None or response .status_code !=200 :
                logger .error ("Volcengine TTS error or request failed")
                return np .zeros (0 ,dtype =np .float32 ),None ,24000 

            result =response .json ()
            if result .get ("code")!=3000 :
                logger .error (f"Volcengine TTS api error: {result }")
                return np .zeros (0 ,dtype =np .float32 ),None ,24000 

            audio_bytes =base64 .b64decode (result ["data"])
            audio_np =np .frombuffer (audio_bytes ,dtype =np .int16 ).astype (np .float32 )/32768.0 
            return audio_np ,None ,24000 
        except httpx .HTTPStatusError as e :
            logger .error (f"Volcengine TTS HTTP error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 
        except httpx .RequestError as e :
            logger .error (f"Volcengine TTS request error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 
        except Exception as e :
            logger .error (f"Volcengine TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),None ,24000 

    async def close (self ):
        await self ._client .aclose ()
