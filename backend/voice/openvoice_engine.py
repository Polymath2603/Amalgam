"""
OpenVoice v2 engine — local voice cloning via MeloTTS + ToneColorConverter.
Runs on CPU to avoid VRAM conflict with LLM.
"""
import os 
import threading 
import logging 
import numpy as np 

logger =logging .getLogger (__name__ )


class OpenVoiceEngine :
    """Wraps MeloTTS + OpenVoice ToneColorConverter for voice cloning."""

    def __init__ (self ,checkpoints_dir ="checkpoints_v2",device ="cpu",language ="EN"):
        self .device =device 
        self .language =language 
        self .checkpoints_dir =checkpoints_dir 
        self ._converter =None 
        self ._melo_model =None 
        self ._source_se =None 
        self ._speaker_cache ={}
        self ._loaded =False 
        self ._load_lock =threading .Lock ()

    def _ensure_loaded (self ):
        """Lazy-load models on first use. Thread-safe."""
        if self ._loaded :
            return 
        with self ._load_lock :
            if self ._loaded :
                return 

        try :
            import torch 

            if not hasattr (torch .nn .Module ,'_original_to'):
                torch .nn .Module ._original_to =torch .nn .Module .to 
                def _patched_to (self ,*args ,**kwargs ):
                    for param in self .parameters ():
                        if param .device .type =='meta':
                            device =args [0 ]if args else kwargs .get ('device','cpu')
                            return self .to_empty (device =device )
                    return torch .nn .Module ._original_to (self ,*args ,**kwargs )
                torch .nn .Module .to =_patched_to 

            from openvoice .api import ToneColorConverter 
            from melo .api import TTS 
            self ._torch =torch 
        except ImportError as e :
            raise RuntimeError (
            "OpenVoice dependencies not installed.\n"
            "Install from source:\n"
            "  1. git clone https://github.com/myshell-ai/OpenVoice.git\n"
            "  2. cd OpenVoice && pip install -e .\n"
            "  3. pip install git+https://github.com/myshell-ai/MeloTTS.git\n"
            "  4. python -m unidic download\n"
            "  5. Download checkpoints_v2/ from the OpenVoice README S3 link\n"
            "     and place it in the project root"
            )from e 

        ckpt_dir =os .path .join (self .checkpoints_dir ,"converter")
        config_path =os .path .join (ckpt_dir ,"config.json")
        ckpt_path =os .path .join (ckpt_dir ,"checkpoint.pth")

        if not os .path .exists (config_path ):
            raise FileNotFoundError (
            f"OpenVoice checkpoints not found at {ckpt_dir }. "
            "Download from the OpenVoice README."
            )


        self ._converter =ToneColorConverter (config_path ,device =self .device )
        self ._converter .load_ckpt (ckpt_path )


        lang_map ={"EN":"EN","EN_NEWEST":"EN_NEWEST","JP":"JP","ZH":"ZH"}
        melo_lang =lang_map .get (self .language ,"EN")
        self ._melo_model =TTS (language =melo_lang ,device =self .device )
        self ._speaker_id =list (self ._melo_model .hps .data .spk2id .values ())[0 ]


        speaker_key =list (self ._melo_model .hps .data .spk2id .keys ())[0 ].lower ().replace ("_","-")
        ses_dir =os .path .join (self .checkpoints_dir ,"base_speakers","ses")
        se_path =os .path .join (ses_dir ,f"{speaker_key }.pth")
        if os .path .exists (se_path ):
            self ._source_se =self ._torch .load (se_path ,map_location =self .device )
        else :
            logger .warning (f"Source speaker embedding not found: {se_path }")

        self ._loaded =True 
        logger .info ("OpenVoice engine loaded successfully")

    def get_speaker_embedding (self ,ref_audio_path :str ):
        """Extract and cache speaker embedding from reference audio or .pth file."""
        if ref_audio_path in self ._speaker_cache :
            return self ._speaker_cache [ref_audio_path ]

        self ._ensure_loaded ()

        if not os .path .exists (ref_audio_path ):
            raise FileNotFoundError (f"Reference audio not found: {ref_audio_path }")


        if ref_audio_path .endswith ('.pth'):
            target_se =self ._torch .load (ref_audio_path ,map_location =self .device )
        else :

            from openvoice import se_extractor 
            target_se ,_ =se_extractor .get_se (
            ref_audio_path ,self ._converter ,vad =True 
            )

        self ._speaker_cache [ref_audio_path ]=target_se 
        return target_se 

    def synthesize (self ,text :str ,ref_audio_path :str )->tuple :
        """Synthesize text with cloned voice. Returns (float32_array, sample_rate)."""
        import tempfile 

        self ._ensure_loaded ()

        if not ref_audio_path :
            raise ValueError ("ref_audio_path is required for OpenVoice synthesis")

        target_se =self .get_speaker_embedding (ref_audio_path )


        fd ,src_path =tempfile .mkstemp (suffix =".wav")
        os .close (fd )
        try :
            self ._melo_model .tts_to_file (text ,self ._speaker_id ,src_path ,speed =1.0 )


            audio_np =self ._converter .convert (
            audio_src_path =src_path ,
            src_se =self ._source_se ,
            tgt_se =target_se ,
            output_path =None ,
            message ="@MyShell"
            )

            sr =self ._converter .hps .data .sampling_rate 
            return audio_np ,sr 

        finally :
            try :
                os .remove (src_path )
            except OSError :
                pass 

    def is_available (self )->bool :
        """Check if OpenVoice can be used (deps installed + checkpoints exist)."""
        try :
            import openvoice 
            import melo 
            ckpt =os .path .join (self .checkpoints_dir ,"converter","config.json")
            return os .path .exists (ckpt )
        except ImportError :
            return False 
