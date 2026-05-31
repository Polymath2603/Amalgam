"""ElevenLabs TTS provider — high-quality cloud TTS with alignment data."""
import io 
import json 
import logging 
import httpx 
import numpy as np 
from scipy .io import wavfile 

from .base import TTSProvider 
from .word_to_viseme import build_viseme_schedule 

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

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ()or not self ._api_key :
            if not self ._api_key :
                logger .warning ("ElevenLabs API key not configured")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        voice_id =self .voice if self .voice else "21m00Tcm4TlvDq8ikWAM"
        url =f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id }/stream?output_format=mp3_44100_128"

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

            async with self ._client .stream ("POST",url ,json =body ,headers =headers )as response :
                if response .status_code !=200 :
                    error_body =await response .aread ()
                    logger .error (f"ElevenLabs API error {response .status_code }: {error_body [:200 ]}")
                    return np .zeros (0 ,dtype =np .float32 ),[],16000 

                mp3_chunks =[]
                alignment_data =None 
                async for line in response .aiter_lines ():
                    if not line :
                        continue 

                    if line .startswith ('{'):
                        try :
                            data =json .loads (line )
                            if 'alignment'in data :
                                alignment_data =data ['alignment']
                        except json .JSONDecodeError :
                            pass 
                    else :

                        pass 

                mp3_data =b''
                async for chunk in response .aiter_bytes ():
                    mp3_chunks .append (chunk )
                mp3_data =b''.join (mp3_chunks )

            sr ,audio_np =self ._decode_mp3 (mp3_data )
            if len (audio_np )==0 :
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            viseme_schedule =[]
            if alignment_data :
                viseme_schedule =self ._alignment_to_viseme_schedule (alignment_data ,sr ,len (audio_np ))
            else :
                logger .debug ("ElevenLabs: no alignment data received, using empty schedule")

            return audio_np ,viseme_schedule ,sr 

        except Exception as e :
            logger .error (f"ElevenLabs TTS Error: {type (e ).__name__ }: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

    def _alignment_to_viseme_schedule (self ,alignment :dict ,sr :int ,total_samples :int )->list :
        """Convert ElevenLabs alignment data to viseme schedule."""
        chars =alignment .get ('characters',[])
        char_starts =alignment .get ('character_start_times_seconds',[])
        char_ends =alignment .get ('character_end_times_seconds',[])

        if not chars or not char_starts :
            return []

        word_boundaries =[]
        current_word =""
        word_start =None 
        word_end =None 

        for i ,ch in enumerate (chars ):
            start =char_starts [i ]if i <len (char_starts )else 0 
            end =char_ends [i ]if i <len (char_ends )else start 

            if ch .isalpha ():
                if not current_word :
                    word_start =start 
                current_word +=ch 
                word_end =end 
            else :
                if current_word :
                    word_boundaries .append ({
                    "text":current_word ,
                    "start":word_start ,
                    "end":word_end ,
                    })
                    current_word =""

        if current_word :
            word_boundaries .append ({
            "text":current_word ,
            "start":word_start ,
            "end":word_end ,
            })

        return build_viseme_schedule (word_boundaries )

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
