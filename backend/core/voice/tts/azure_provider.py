"""Azure TTS provider — Microsoft Cognitive Services with viseme events."""
import asyncio 
import logging 
import numpy as np 

from .base import TTSProvider 

logger =logging .getLogger (__name__ )

AZURE_VISEME_MAP ={
0 :'sil',1 :'PP',2 :'FF',3 :'TH',4 :'DD',
5 :'kk',6 :'CH',7 :'SS',8 :'nn',9 :'RR',
10 :'aa',11 :'E',12 :'I',13 :'O',14 :'U',
15 :'aa',16 :'E',17 :'I',18 :'O',19 :'U',
20 :'RR',21 :'nn',
}

TICKS_PER_MS =10_000 

# Import speechsdk once at module level
try :
    import azure .cognitiveservices .speech as speechsdk 
    _AZURE_SPEECH_AVAILABLE =True 
except ImportError :
    _AZURE_SPEECH_AVAILABLE =False 
    speechsdk =None 


class AzureTTSProvider (TTSProvider ):
    def __init__ (self ,voice ="en-US-AriaNeural"):
        super ().__init__ (voice )
        self ._api_key =""
        self ._region ="eastus"

    def configure (self ,api_key :str ,region :str ="eastus"):
        self ._api_key =api_key 
        self ._region =region 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if not text .strip ()or not self ._api_key :
            if not self ._api_key :
                logger .warning ("Azure API key not configured")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        if not _AZURE_SPEECH_AVAILABLE :
            logger .error ("azure-cognitiveservices-speech not installed")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        try :
            loop =asyncio .get_event_loop ()
            result =await loop .run_in_executor (None ,self ._synthesize_sync ,text ,emotion )
            return result 
        except Exception as e :
            logger .error (f"Azure TTS error: {e }")
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

    def _synthesize_sync (self ,text :str ,emotion :str )->tuple :
        """Synchronous synthesis using Azure Speech SDK with viseme events."""
        speech_config =speechsdk .SpeechConfig (
        subscription =self ._api_key ,
        region =self ._region ,
        )
        speech_config .set_speech_synthesis_output_format (
        speechsdk .SpeechSynthesisOutputFormat .Riff16Khz16BitMonoPcm 
        )

        prosody =''
        if emotion and emotion !="neutral":
            emotion_map ={
            "happy":("+10%","+2st"),"sad":("-5%","-2st"),
            "angry":("+5%","+3st"),"surprised":("+10%","+3st"),
            "relaxed":("-5%","-2st"),"excited":("+10%","+4st"),
            }
            rate ,pitch =emotion_map .get (emotion ,("0%","0st"))
            prosody =f'<prosody rate="{rate }" pitch="{pitch }">'

        ssml =(
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">'
        f'<voice name="{self .voice }">'
        f'<mstts:viseme type="redlips_front"/>'
        f'{prosody }{text }{""if not prosody else "</prosody>"}'
        f'</voice></speak>'
        )

        synthesizer =speechsdk .SpeechSynthesizer (speech_config =speech_config )

        viseme_schedule =[]

        def on_viseme (evt ):
            viseme_id =evt .viseme_id 
            audio_offset_ms =evt .audio_offset /TICKS_PER_MS 
            viseme_key =AZURE_VISEME_MAP .get (viseme_id ,'aa')
            viseme_schedule .append ({
            'viseme':viseme_key ,
            'start':round (audio_offset_ms /1000 ,4 ),
            'duration':0.0 ,
            })

        synthesizer .viseme_received .connect (on_viseme )

        try :
            result =synthesizer .speak_ssml_async (ssml ).get ()

            if result .reason !=speechsdk .ResultReason .SynthesizingAudioCompleted :
                error =result .cancellation_details 
                logger .error (f"Azure TTS failed: {error .reason } - {error .error_details }")
                return np .zeros (0 ,dtype =np .float32 ),[],16000 

            audio_bytes =result .audio_data 
            audio_np =np .frombuffer (audio_bytes ,dtype =np .int16 ).astype (np .float32 )/32768.0 
            sr =16000 

            for i in range (len (viseme_schedule )):
                if i +1 <len (viseme_schedule ):
                    dur =viseme_schedule [i +1 ]['start']-viseme_schedule [i ]['start']
                else :
                    dur =(len (audio_np )/sr )-viseme_schedule [i ]['start']
                viseme_schedule [i ]['duration']=round (max (dur ,0.01 ),4 )

            logger .debug (f"Azure TTS: {len (audio_np )} samples, {len (viseme_schedule )} visemes")
            return audio_np ,viseme_schedule ,sr 
        finally :
            # Dispose the synthesizer to release native resources
            try :
                synthesizer .dispose () if hasattr (synthesizer ,'dispose')else None 
            except Exception :
                pass 

    async def close (self ):
        # Azure SDK handles its own cleanup via SpeechSynthesizer.dispose()
        pass 
