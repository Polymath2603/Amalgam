import logging 
from typing import Optional ,Callable 

logger =logging .getLogger (__name__ )


class WakeWordRouter :
    SUPPORTED_ENGINES ={"openwakeword"}

    _PROVIDER_CLASSES =None 

    @classmethod 
    def _get_provider_classes (cls ):
        if cls ._PROVIDER_CLASSES is None :
            from .openwakeword_provider import OpenWakeWordProvider 
            cls ._PROVIDER_CLASSES ={
                "openwakeword":OpenWakeWordProvider ,
            }
        return cls ._PROVIDER_CLASSES 

    def __init__ (self ,engine :str ="openwakeword"):
        self ._engine =engine 
        self ._provider =None 
        self ._enabled =False 
        self ._callback =None 

    def set_callback (self ,cb :Callable [[str ],None ]):
        self ._callback =cb 

    def start (self ,on_detected :Optional [Callable [[str ],None ]]=None )->bool :
        if self ._enabled :
            return True 
        if self ._provider is None :
            cb =on_detected or self ._callback 
            provider =self ._create_provider (cb )
            if provider is None :
                return False 
            self ._provider =provider 
        try :
            self ._provider .start ()
            self ._enabled =True 
            return True 
        except Exception as e :
            logger .error (f"Failed to start wake word: {e }")
            return False 

    def stop (self ):
        if self ._provider and self ._enabled :
            try :
                self ._provider .stop ()
            except Exception as e :
                logger .warning (f"Wake word stop error: {e }")
        self ._enabled =False 

    @property 
    def is_listening (self )->bool :
        return self ._enabled and self ._provider is not None and self ._provider .is_running 

    def _create_provider (self ,on_detected ):
        cls =self ._get_provider_classes ().get (self ._engine )
        if cls is None :
            logger .error (f"Unknown wake word engine: {self ._engine }")
            return None 
        return cls (on_detected =on_detected ) 
