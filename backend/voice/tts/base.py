from typing import Tuple 

import numpy as np 


class TTSProvider :
    supported_emotions =[]

    def __init__ (self ,voice ="en-US-AriaNeural"):
        self .voice =voice 

    async def synthesize (self ,text :str ,ref_audio :str =None ,emotion :str ="neutral")->Tuple [np .ndarray ,list ,int ]:
        raise NotImplementedError 
