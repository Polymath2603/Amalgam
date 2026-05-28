"""
LLM Router — thin facade over LiteLLMProvider.

Preserves the existing interface used by Agent and Memory while
delegating all inference to LiteLLM.
"""

import logging 
from typing import AsyncIterator ,List ,Dict ,Any 

import litellm 

from .litellm_provider import LiteLLMProvider 

logger =logging .getLogger (__name__ )


class LLMRouter :
    """Unified LLM router backed by LiteLLM."""

    def __init__ (self ,settings =None ):
        self .settings =settings 
        self ._provider =LiteLLMProvider (settings )

    def reload_settings (self ):
        self ._provider .reload_settings ()

    def supports_native_tools (self )->bool :
        return self ._provider .supports_native_tools ()

    def get_max_output_tokens (self )->int :
        return self ._provider .get_max_output_tokens ()

    def get_context_token_limit (self )->int :
        return self ._provider .get_context_token_limit ()

    async def stream (self ,messages :list ,temperature :float =None )->AsyncIterator [str ]:
        async for token in self ._provider .stream (messages ,temperature ):
            yield token 

    async def stream_with_tools (
    self ,messages :list ,tools :List [Dict [str ,Any ]],temperature :float =None 
    )->AsyncIterator :
        if self .supports_native_tools ():
            async for item in self ._provider .stream_with_tools (messages ,tools ,temperature ):
                yield item 
        else :
            async for token in self ._provider .stream (messages ,temperature ):
                yield token 

    async def generate (self ,messages :list ,temperature :float =None )->str :
        return await self ._provider .generate (messages ,temperature )

    async def get_embedding (self ,text :str )->List [float ]:
        return await self ._provider .get_embedding (text )

    async def fetch_ollama_models (self )->List [str ]:
        """Fetch models from a running Ollama server."""
        import httpx 
        base_url ="http://localhost:11434"
        if self .settings :
            base_url =self .settings .get ("provider.ollama.base_url",base_url )
        try :
            async with httpx .AsyncClient (timeout =10 )as client :
                resp =await client .get (f"{base_url .rstrip ('/')}/api/tags")
                if resp .status_code ==200 :
                    data =resp .json ()
                    return [m ["name"]for m in data .get ("models",[])]
        except Exception as e :
            logger .warning (f"Failed to fetch Ollama models: {e }")
        return []

    async def fetch_gemini_models (self )->List [str ]:
        return sorted (litellm .gemini_models )if hasattr (litellm ,'gemini_models')else []

    async def fetch_openai_compat_models (self ,provider :str )->List [str ]:
        attr =f"{provider }_models"
        if hasattr (litellm ,attr ):
            return sorted (getattr (litellm ,attr ))
        return []

    async def fetch_bedrock_models (self )->List [str ]:
        return sorted (litellm .bedrock_models )if hasattr (litellm ,'bedrock_models')else []

    async def fetch_vertex_models (self )->List [str ]:
        models =set ()
        for attr in dir (litellm ):
            if 'vertex'in attr and attr .endswith ('_models'):
                models .update (getattr (litellm ,attr ))
        return sorted (models )

    async def close (self ):
        await self ._provider .close ()
