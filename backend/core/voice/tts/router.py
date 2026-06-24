import logging 
import asyncio 
import numpy as np 

logger =logging .getLogger (__name__ )


class TTSRouter :
    SUPPORTED_ENGINES ={"edge-tts","openvoice","elevenlabs","openai-tts",
    "speecht5","alltalk","piper","coqui-local","kokoro",
    "azure","dashscope","volcengine","deepgram","mlx","rvc"}

    _PROVIDER_CLASSES =None 

    @classmethod 
    def _get_provider_classes (cls ):
        if cls ._PROVIDER_CLASSES is None :
            from .edge_tts_provider import EdgeTTSProvider 
            from .openvoice_provider import OpenVoiceProvider 
            from .elevenlabs_provider import ElevenLabsProvider 
            from .openai_tts_provider import OpenAITTSProvider 
            from .speecht5_provider import SpeechT5Provider 
            from .alltalk_provider import AllTalkProvider 
            from .piper_provider import PiperProvider 
            from .coqui_local_provider import CoquiLocalProvider 
            from .kokoro_provider import KokoroProvider 
            from .azure_provider import AzureTTSProvider 
            from .dashscope_provider import DashScopeProvider 
            from .volcengine_provider import VolcengineProvider 
            from .deepgram_provider import DeepgramProvider 
            from .mlx_provider import MLXProvider 
            from .rvc_provider import RVCProvider 
            cls ._PROVIDER_CLASSES ={
            "edge-tts":EdgeTTSProvider ,
            "openvoice":OpenVoiceProvider ,
            "elevenlabs":ElevenLabsProvider ,
            "openai-tts":OpenAITTSProvider ,
            "speecht5":SpeechT5Provider ,
            "alltalk":AllTalkProvider ,
            "piper":PiperProvider ,
            "coqui-local":CoquiLocalProvider ,
            "kokoro":KokoroProvider ,
            "azure":AzureTTSProvider ,
            "dashscope":DashScopeProvider ,
            "volcengine":VolcengineProvider ,
            "deepgram":DeepgramProvider ,
            "mlx":MLXProvider ,
            "rvc":RVCProvider ,
            }
        return cls ._PROVIDER_CLASSES 

    def __init__ (self ,voice ="en-US-AriaNeural",engine ="edge-tts"):
        self .engine =engine 
        self ._lock =asyncio .Lock ()
        self ._providers ={}
        self ._voice =voice 

    def _ensure (self ,name ,voice =None ):
        if name not in self ._providers :
            cls =self ._get_provider_classes ().get (name )
            if cls is None :
                raise ValueError (f"Unknown TTS engine: {name }")
            self ._providers [name ]=cls (voice or self ._voice )
        return self ._providers [name ]

    def _current (self ):
        return self ._ensure (self .engine )

    @property 
    def voice (self ):
        return self ._voice 

    @voice .setter 
    def voice (self ,val ):
        self ._voice =val 
        for name ,p in list (self ._providers .items ()):
            try :
                p .voice =val 
            except Exception as e :
                logger .warning ("Failed to set voice on provider '%s': %s", name ,e )

    def get_supported_emotions (self ):
        return self ._current ().supported_emotions 

    def get_openvoice_loaded (self ):
        ov =self ._ensure ("openvoice")
        return ov .get_openvoice_loaded ()

    def configure_elevenlabs (self ,api_key: "REDACTED"):
        self ._ensure ("elevenlabs").configure (api_key ,model )

    def configure_openai_tts (self ,api_key :str ,model :str ="tts-1",base_url :str =None ):
        self ._ensure ("openai-tts").configure (api_key ,model ,base_url )

    def configure_alltalk (self ,url :str =None ,language :str ="en",version :str ="v2",
    rvc_voice :str ="",rvc_pitch :str ="0"):
        self ._ensure ("alltalk").configure (url ,language ,version ,rvc_voice ,rvc_pitch )

    def configure_piper (self ,url :str =None ):
        self ._ensure ("piper").configure (url )

    def configure_coqui (self ,url :str =None ,speaker_id :str =""):
        self ._ensure ("coqui-local").configure (url ,speaker_id )

    def configure_kokoro (self ,url :str =None ):
        self ._ensure ("kokoro").configure (url )

    def configure_azure (self ,api_key :str ,region :str ="eastus"):
        self ._ensure ("azure").configure (api_key ,region )

    def configure_dashscope (self ,api_key :str ,model :str ="cosyvoice-v1"):
        self ._ensure ("dashscope").configure (api_key ,model )

    def configure_volcengine (self ,app_id :str ,access_token :str ,cluster :str ="volcano_tts"):
        self ._ensure ("volcengine").configure (app_id ,access_token ,cluster )

    def configure_deepgram (self ,api_key :str ,model :str ="aura-2"):
        self ._ensure ("deepgram").configure (api_key ,model )

    def configure_rvc (self ,url :str =None ,f0_up_key :int =0 ,f0_method :str ="rmvpe"):
        rvc =self ._ensure ("rvc")
        rvc .configure (url ,f0_up_key ,f0_method )

        # Store a reference to the current engine's provider as RVC's upstream
        # This way, if self.engine changes later, the upstream remains the
        # provider that was current at configure-time.
        if self .engine !="rvc":
            upstream =self ._ensure (self .engine )
            rvc .set_tts_provider (upstream )

    _SR_MAP ={
    "elevenlabs":44100 ,
    "openai-tts":24000 ,
    "speecht5":16000 ,
    "edge-tts":16000 ,
    "alltalk":24000 ,
    "piper":22050 ,
    "coqui-local":24000 ,
    "kokoro":24000 ,
    "openvoice":22050 ,
    "azure":16000 ,
    "dashscope":16000 ,
    "volcengine":24000 ,
    "deepgram":24000 ,
    "mlx":24000 ,
    "rvc":24000 ,
    }

    async def synthesize_parallel (
        self,
        sentences: list[str],
        *,
        ref_audio: str | None = None,
        emotion: str = "neutral",
        max_concurrent: int = 3,
        translation_service=None,
    ) -> list[dict]:
        """Synthesize multiple sentences concurrently while preserving order.

        Each result dict has keys:
          idx       — original index in *sentences*
          text      — the input text (or translated text if translation_service given)
          audio     — numpy array of audio samples
          visemes   — viseme schedule list or None
          sr        — sample rate
          error     — error string or None

        When *translation_service* is provided, each sentence is translated
        before synthesis (concurrently with other translations).
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _work(idx: int, text: str) -> dict:
            # Translate if service is available (before acquiring semaphore — translation
            # is generally fast and network-bound, but we bound it loosely)
            synth_text = text
            if translation_service is not None:
                try:
                    synth_text = await translation_service.translate(text)
                except Exception as e:
                    logger.warning("Translation error for sentence %d: %s", idx, e)
                    synth_text = text  # fall back to original

            async with sem:
                try:
                    result = await self.synthesize(synth_text, ref_audio=ref_audio, emotion=emotion)
                    audio_np, visemes, sr = result
                    return {
                        "idx": idx,
                        "text": synth_text,
                        "audio": audio_np,
                        "visemes": visemes,
                        "sr": sr,
                        "error": None,
                    }
                except Exception as e:
                    logger.error("Parallel TTS sentence %d failed: %s", idx, e)
                    return {
                        "idx": idx,
                        "text": synth_text,
                        "audio": np.zeros(0, dtype=np.float32),
                        "visemes": [],
                        "sr": 16000,
                        "error": str(e),
                    }

        tasks = [_work(i, s) for i, s in enumerate(sentences)]
        results = await asyncio.gather(*tasks)
        # Sort by original index to guarantee ordering
        results.sort(key=lambda r: r["idx"])
        return results

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple [np .ndarray ,list [dict ]|None ,int ]:
        if not text .strip ():
            return np .zeros (0 ,dtype =np .float32 ),[],16000 

        provider =self ._current ()

        if self .engine =="openvoice":
            async with self ._lock :
                return await self ._do_synthesize (provider ,text ,ref_audio ,emotion =emotion )
        else :
            return await self ._do_synthesize (provider ,text ,ref_audio ,emotion =emotion )

    async def _do_synthesize (self ,provider ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple :
        if self .engine =="openvoice":
            # OpenVoice with fallback — separate try/except for each stage
            try :
                result =await provider .synthesize (text ,ref_audio =ref_audio ,emotion =emotion )
                if isinstance (result ,tuple )and len (result )>=3 :
                    audio ,visemes ,*_ =result 
                else :
                    audio ,visemes =result 
                if len (audio )>0 :
                    return audio ,visemes ,22050 
            except Exception as e :
                logger .info ("OpenVoice primary synthesis failed: %s, falling back to edge-tts", e)

            # Fallback
            try :
                fallback =self ._ensure ("edge-tts")
                result =await fallback .synthesize (text ,ref_audio =ref_audio ,emotion =emotion )
                if isinstance (result ,tuple )and len (result )>=3 :
                    audio ,visemes ,*_ =result 
                else :
                    audio ,visemes =result 
                return audio ,visemes ,16000 
            except Exception as e :
                logger .error ("OpenVoice fallback to edge-tts also failed: %s", e)
                return np .zeros (0 ,dtype =np .float32 ),[],self ._SR_MAP .get (self .engine ,16000 )
        else :
            try :
                result =await provider .synthesize (text ,ref_audio =ref_audio ,emotion =emotion )
                if isinstance (result ,tuple )and len (result )>=3 :
                    audio ,visemes ,sr =result 
                else :
                    audio ,visemes =result 
                    sr =self ._SR_MAP .get (self .engine ,16000 )
                return audio ,visemes ,sr 
            except Exception as e :
                logger .error (f"TTS synthesis failed for engine '{self .engine }': {type (e ).__name__ }: {e }")
                return np .zeros (0 ,dtype =np .float32 ),[],self ._SR_MAP .get (self .engine ,16000 )

    async def close(self):
        """Close all cached providers, releasing HTTP clients and other resources."""
        for name, provider in list(self._providers.items()):
            try:
                if hasattr(provider, 'close') and callable(provider.close):
                    if asyncio.iscoroutinefunction(provider.close):
                        await provider.close()
                    else:
                        provider.close()
            except Exception as e:
                logger.warning("Error closing TTS provider '%s': %s", name, e)
        self._providers.clear()
