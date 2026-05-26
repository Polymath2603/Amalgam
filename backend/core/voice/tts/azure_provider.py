"""Azure TTS provider — Microsoft Cognitive Services."""
import logging 
import uuid 
import numpy as np 
import httpx 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class AzureTTSProvider (TTSProvider ):
    def __init__ (self ,voice ="en-US-AriaNeural"):
        super ().__init__ (voice )
        self ._api_key =""
        self ._region ="eastus"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,api_key :str ,region :str ="eastus"):
        self ._api_key =api_key 
        self ._region =region 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ()or not self ._api_key :
            if not self ._api_key :
                logger .warning ("Azure API key not configured")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        ssml =(
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">'
        f'<voice name="{self .voice }">'
        f'{text }'
        f'</voice></speak>'
        )

        url =f"https://{self ._region }.tts.speech.microsoft.com/cognitiveservices/v1"
        headers ={
        "Ocp-Apim-Subscription-Key":self ._api_key ,
        "Content-Type":"application/ssml+xml",
        "X-Microsoft-OutputFormat":"riff-16khz-16bit-mono-pcm",
        "User-Agent":"amalgam",
        "X-RequestId":str (uuid .uuid4 ()),
        }

        try :
            response =await self ._client .post (url ,content =ssml .encode ("utf-8"),headers =headers )
            if response .status_code !=200 :
                logger .error (f"Azure TTS error {response .status_code }: {response .text [:200 ]}")
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            audio_np =np .frombuffer (response .content ,dtype =np .int16 ).astype (np .float32 )/32767.0 
            visemes =["A"]*(len (text )//2 )
            return audio_np ,visemes ,16000 
        except Exception as e :
            logger .error (f"Azure TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

    async def close (self ):
        await self ._client .aclose ()
