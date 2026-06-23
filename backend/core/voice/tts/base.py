import logging 
import asyncio 
import io 
import struct 
import wave 

import numpy as np 

logger =logging .getLogger (__name__ )


def decode_wav (audio_bytes :bytes )->tuple [np .ndarray ,int ]:
    """
    Decode WAV bytes into a float32 numpy array.

    Args:
        audio_bytes: Raw WAV file bytes.

    Returns:
        (audio_np, sample_rate)
        On failure returns (np.zeros(0, dtype=np.float32), 0).
    """
    try :
        with io .BytesIO (audio_bytes )as buf :
            with wave .open (buf ,"rb")as wf :
                sr =wf .getframerate ()
                frames =wf .readframes (wf .getnframes ())
                audio_np =np .frombuffer (frames ,dtype =np .int16 ).astype (np .float32 )/32768.0
        return audio_np ,sr
    except (wave .Error ,EOFError ,struct .error ,Exception )as e :
        logger .warning ("Failed to decode WAV: %s",e )
        return np .zeros (0 ,dtype =np .float32 ),0


async def retry_http (client ,method :str ,url :str ,*,
                      max_retries :int =2 ,
                      backoff :float =0.5 ,
                      **kwargs ):
    """
    Retry an HTTP request on transient errors (timeout, connection, 5xx).

    Args:
        client: An httpx.AsyncClient instance.
        method: HTTP method ('GET', 'POST', etc.).
        url: Request URL.
        max_retries: Maximum number of retry attempts.
        backoff: Base delay in seconds between retries.
        **kwargs: Additional arguments passed to client.request().

    Returns:
        httpx.Response on success, None if all retries are exhausted.
    """
    import httpx
    last_exc =None
    for attempt in range (1 +max_retries ):
        try :
            response =await client .request (method ,url ,**kwargs )
            if response .status_code <500 :
                return response
            # 5xx — retry unless this was the last attempt
            if attempt <max_retries :
                await asyncio .sleep (backoff *(2 **attempt ))
            else :
                return response
        except (httpx .TimeoutException ,httpx .ConnectError ,httpx .RemoteProtocolError )as e :
            last_exc =e
            logger .warning ("HTTP %s %s transient error (attempt %d/%d): %s",
                            method ,url ,attempt +1 ,max_retries +1 ,e )
            if attempt <max_retries :
                await asyncio .sleep (backoff *(2 **attempt ))
            else :
                logger .error ("HTTP %s %s failed after %d retries: %s",
                              method ,url ,max_retries +1 ,last_exc )
                return None
    return None


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
