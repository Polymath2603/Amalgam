from typing import Optional 

import numpy as np 


class TTSProvider :
    supported_emotions =[]

    def __init__ (self ,voice ="en-US-AriaNeural"):
        self .voice =voice 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->tuple [np .ndarray ,list [dict ]|None ,int ]:
        """
        Synthesize speech from text.

        Returns:
            (audio_np, viseme_schedule, sample_rate)
            viseme_schedule is a list of {"viseme": str, "start": float, "duration": float}
            or None if the provider doesn't support lip sync metadata.
        """
        raise NotImplementedError 
