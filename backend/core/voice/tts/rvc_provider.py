"""RVC voice conversion provider — local RVC WebUI API."""
import json 
import logging 
import numpy as np 
import httpx 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class RVCProvider (TTSProvider ):
    def __init__ (self ,voice =""):
        super ().__init__ (voice )
        self ._url ="http://127.0.0.1:7897"
        self ._f0_up_key =0 
        self ._f0_method ="rmvpe"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))
        self ._tts_provider =None 

    def configure (self ,url :str =None ,f0_up_key :int =0 ,f0_method :str ="rmvpe"):
        if url :
            self ._url =url .rstrip ("/")
        self ._f0_up_key =f0_up_key 
        self ._f0_method =f0_method 

    def set_tts_provider (self ,provider ):
        """Set the TTS provider that generates the source audio for RVC conversion."""
        self ._tts_provider =provider 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],24000 

        if self ._tts_provider is None :
            logger .error ("RVC requires a TTS provider set via set_tts_provider()")
            return np .zeros (0 ,dtype =np .float32 ),[],24000 


        source_result =await self ._tts_provider .synthesize (text ,ref_audio =ref_audio ,emotion =emotion )
        if isinstance (source_result ,tuple )and len (source_result )>=3 :
            source_audio ,_ ,source_sr =source_result 
        else :
            source_audio ,_ =source_result 
            source_sr =24000 

        if len (source_audio )==0 :
            return np .zeros (0 ,dtype =np .float32 ),[],24000 


        import io 
        import wave 
        import struct 

        buf =io .BytesIO ()
        with wave .open (buf ,"wb")as wf :
            wf .setnchannels (1 )
            wf .setsampwidth (2 )
            wf .setframerate (source_sr )
            int_audio =(source_audio *32767.0 ).astype (np .int16 )
            wf .writeframes (int_audio .tobytes ())
        wav_bytes =buf .getvalue ()


        files ={"audio":("input.wav",wav_bytes ,"audio/wav")}
        data ={
        "f0_up_key":str (self ._f0_up_key ),
        "f0_method":self ._f0_method ,
        "index_rate":"0.5",
        "filter_radius":"3",
        "resample_sr":"24000",
        "rms_mix_rate":"0.25",
        "protect":"0.33",
        }
        if self .voice :
            data ["model"]=self .voice 

        try :
            resp =await self ._client .post (
            f"{self ._url }/voice-change",
            data =data ,
            files =files ,
            )
            if resp .status_code !=200 :
                logger .error (f"RVC error {resp .status_code }: {resp .text [:200 ]}")
                return np .zeros (0 ,dtype =np .float32 ),[],24000 


            audio_np =np .frombuffer (resp .content ,dtype =np .int16 ).astype (np .float32 )/32767.0 
            visemes =["A"]*(len (text )//2 )
            return audio_np ,visemes ,24000 
        except Exception as e :
            logger .error (f"RVC error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],24000 

    async def close (self ):
        await self ._client .aclose ()
