"""
Token estimation utilities.
Uses tiktoken when available for OpenAI-compatible models, falls back to
character-based heuristic (~4 chars/token) for any text.

Calibrated for tokenizer families:
- OpenAI cl100k_base / o200k_base: ~4 chars/token → tiktoken
- LLaMA / Mistral SentencePiece: ~3.2 chars/token → char heuristic
"""
import copy
import functools
import logging 
from typing import Optional 

logger =logging .getLogger (__name__ )

_TIKTOKEN_AVAILABLE =False

try :
    import tiktoken 
    _TIKTOKEN_AVAILABLE =True 
except ImportError :
    pass 


_CHARS_PER_TOKEN =4.0 



_SENTENCEPIECE_PREFIXES =(
"groq/llama","groq/mixtral","groq/llama-3",
"mistral/",
"together_ai/mistral","together_ai/llama",
"ollama/llama","ollama/mistral","ollama/mixtral",
"bedrock/llama","bedrock/mistral",
"vertex_ai/llama","vertex_ai/mistral",
)
_SENTENCEPIECE_CPT =3.2 

_ENCODING_MAP ={
"gpt-4":"cl100k_base",
"gpt-4o":"o200k_base",
"gpt-4o-mini":"o200k_base",
"gpt-3.5":"cl100k_base",
"text-embedding":"cl100k_base",
}


@functools.lru_cache(maxsize=8)
def _get_encoding (model :Optional [str ]=None ):
    """Get tiktoken encoding for model, caching result."""
    if not _TIKTOKEN_AVAILABLE :
        return None 
    if model is None :
        model ="gpt-4"
    enc_name =_ENCODING_MAP .get (model )
    if enc_name is None :

        for prefix ,name in _ENCODING_MAP .items ():
            if model .startswith (prefix ):
                enc_name =name 
                break 
    if enc_name is None :
        enc_name ="cl100k_base"
    try :
        return tiktoken .get_encoding (enc_name )
    except Exception :
        logger .debug (f"tiktoken encoding {enc_name } not available")
        return None 


def estimate_tokens (text :str ,model :Optional [str ]=None )->int :
    """Estimate token count for text.

    Uses tiktoken for OpenAI models (when installed), otherwise falls back
    to a character-based heuristic (~4 chars/token). For SentencePiece-based
    models (LLaMA, Mistral), uses a tighter 3.2 chars/token ratio since
    tiktoken's cl100k_base undercounts by 30-40% on structured text.
    """
    if not text :
        return 0 

    model_str =model or ""
    if any (model_str .startswith (p )for p in _SENTENCEPIECE_PREFIXES ):
        return max (1 ,round (len (text )/_SENTENCEPIECE_CPT ))

    enc =_get_encoding (model )if _TIKTOKEN_AVAILABLE else None 
    if enc is not None :
        try :
            return len (enc .encode (text ))
        except Exception :
            logger .debug ("tiktoken encode failed for model=%s",model )

    return max (1 ,round (len (text )/_CHARS_PER_TOKEN ))


def truncate_to_token_limit (text :str ,max_tokens :int ,model :Optional [str ]=None )->str :
    """Truncate text to fit within a token limit, preserving whole words."""
    if max_tokens <=0 :
        return ""
    tokens =estimate_tokens (text ,model )
    if tokens <=max_tokens :
        return text 

    suffix ="\n...[truncated]"
    suffix_tokens =estimate_tokens (suffix ,model )
    content_budget =max (0 ,max_tokens -suffix_tokens )

    lo ,hi =0 ,len (text )
    while lo <hi :
        mid =(lo +hi +1 )//2 
        t =estimate_tokens (text [:mid ],model )
        if t <=content_budget :
            lo =mid 
        else :
            hi =mid -1 

    truncated =text [:lo ]
    last_space =truncated .rfind (" ")
    if last_space >len (truncated )*0.7 :
        truncated =truncated [:last_space ]
    result =truncated +suffix
    if len (result )>=len (text ):
        return suffix
    return result


def estimate_message_list_tokens (messages :list ,model :Optional [str ]=None )->int :
    """Estimate total tokens for a list of message dicts with 'role' and 'content' keys."""
    total =0 
    for msg in messages :
        total +=estimate_tokens (msg .get ("role",""),model )
        total +=estimate_tokens (msg .get ("content",""),model )
        total +=4 
    total +=2 
    return total 


def select_messages_within_budget (
messages :list ,
budget :int ,
model :Optional [str ]=None 
)->list :
    """Select messages from the end (most recent) that fit within token budget.
    
    Returns messages in chronological order.
    """
    if budget <= 0 :
        return []
    total =0 
    selected =[]
    for msg in reversed (messages ):
        msg_tokens =estimate_tokens (msg .get ("role",""),model )+estimate_tokens (msg .get ("content",""),model )+4 
        if total +msg_tokens >budget :

            if not selected :
                role_tokens =estimate_tokens (msg .get ("role",""),model )
                content_budget =budget -role_tokens -4
                if content_budget >0 :
                    truncated =truncate_to_token_limit (msg .get ("content",""),content_budget ,model )
                    selected .insert (0 ,{**msg ,"content":truncated })
            break 
        total +=msg_tokens 
        selected .insert (0 ,copy .deepcopy (msg ))
    return selected 
