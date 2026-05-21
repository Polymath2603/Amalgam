"""ElevenLabs TTS provider — high-quality cloud TTS (ported from Amica)."""
import io 
import logging 
import httpx 
import numpy as np 
from scipy .io import wavfile 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )


class ElevenLabsProvider (TTSProvider ):
    def __init__ (self ,voice =""):
        super ().__init__ (voice )
        self ._api_key =""
        self ._model ="eleven_multilingual_v2"
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (60.0 ,connect =10.0 ))

    def configure (self ,api_key: "REDACTED"):
        self ._api_key =api_key 
        self ._model =model 

    async def synthesize (self ,text :str ,ref_audio :str =None )->tuple :
        if not text .strip ()or not self ._api_key :
            if not self ._api_key :
                logger .warning ("ElevenLabs API key not configured")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        voice_id =self .voice if self .voice else "21m00Tcm4TlvDq8ikWAM"
        url =f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id }?optimize_streaming_latency=0&output_format=mp3_44100_128"

        body ={
        "text":text ,
        "model_id":self ._model ,
        "voice_settings":{
        "stability":0 ,
        "similarity_boost":0 ,
        "style":0 ,
        "use_speaker_boost":True ,
        },
        }
        headers ={
        "Content-Type":"application/json",
        "Accept":"audio/mpeg",
        "xi-api-key":self ._api_key ,
        }

        try :
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code !=200 :
                logger .error (f"ElevenLabs API error {response .status_code }: {response .text [:200 ]}")
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            mp3_data =response .content 
            sr ,audio_np =self ._decode_mp3 (mp3_data )
            if len (audio_np )==0 :
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            visemes =["A"]*(len (text )//2 )
            return audio_np ,visemes ,sr 

        except Exception as e :
            logger .error (f"ElevenLabs TTS Error: {type (e ).__name__ }: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

    def _decode_mp3 (self ,mp3_data :bytes )->tuple :
        try :
            import subprocess as sp 
            import tempfile 
            import os 

            fd_mp3 ,tmp_mp3 =tempfile .mkstemp (suffix =".mp3")
            fd_wav ,tmp_wav =tempfile .mkstemp (suffix =".wav")
            os .close (fd_mp3 )
            os .close (fd_wav )
            try :
                with open (tmp_mp3 ,"wb")as f :
                    f .write (mp3_data )
                proc =sp .run (
                ["ffmpeg","-y","-i",tmp_mp3 ,"-ar","44100","-ac","1",tmp_wav ],
                capture_output =True ,timeout =30 ,
                )
                if proc .returncode ==0 :
                    sr ,data =wavfile .read (tmp_wav )
                    if data .dtype ==np .int16 :
                        audio_np =data .astype (np .float32 )/32768.0 
                    else :
                        audio_np =data .astype (np .float32 )
                    return sr ,audio_np 
            finally :
                for p in (tmp_mp3 ,tmp_wav ):
                    try :
                        os .remove (p )
                    except OSError :
                        pass 
        except Exception as e :
            logger .error (f"MP3 decode error: {e }")
        return 44100 ,np .zeros (0 ,dtype =np .float32 )

    async def close (self ):
        await self ._client .aclose ()
