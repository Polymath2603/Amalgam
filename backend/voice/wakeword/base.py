import abc 
from typing import Callable ,Optional 


class WakeWordProvider (abc .ABC ):
    def __init__ (self ,on_detected :Optional [Callable [[str ],None ]]=None ):
        self ._on_detected =on_detected 

    @abc .abstractmethod 
    def start (self ):
        ...

    @abc .abstractmethod 
    def stop (self ):
        ...

    @abc .abstractmethod 
    def feed_audio (self ,chunk :bytes ):
        ...

    @property 
    @abc .abstractmethod 
    def is_running (self )->bool :
        ...
