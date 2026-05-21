import logging 
from typing import AsyncIterator ,List 

from .gemini import GeminiProvider 
from .ollama import OllamaProvider 
from .openai_compat import OpenAICompatProvider 
from .claude import ClaudeProvider 
from .llamacpp import LlamaCppProvider 
from .koboldai import KoboldAIProvider 

logger =logging .getLogger (__name__ )


class LLMRouter :
    OPENAI_COMPAT ={"openrouter","zai","siliconflow","groq","chatgpt"}
    NATIVE_PROVIDERS ={"gemini","ollama","claude","koboldai","llamacpp"}

    def __init__ (self ,settings =None ):
        self .settings =settings 
        self .provider ="gemini"
        self ._gemini =None 
        self ._ollama =None 
        self ._claude =None 
        self ._llamacpp =None 
        self ._koboldai =None 
        self ._openai_compat ={}
        self ._load_config ()

    def _load_config (self ):
        if self .settings :
            self .provider =self .settings .get ("provider.active","gemini")
        self ._gemini =GeminiProvider (self .settings )
        self ._ollama =OllamaProvider (self .settings )
        self ._claude =ClaudeProvider (self .settings )
        self ._llamacpp =LlamaCppProvider (self .settings )
        self ._koboldai =KoboldAIProvider (self .settings )
        self ._openai_compat ={}
        for p in self .OPENAI_COMPAT :
            self ._openai_compat [p ]=OpenAICompatProvider (p ,self .settings )

    def reload_settings (self ):
        if self .settings :
            self .settings .load ()
        self ._load_config ()

    def _provider_instance (self ):
        if self .provider =="gemini":
            return self ._gemini 
        elif self .provider =="ollama":
            return self ._ollama 
        elif self .provider =="claude":
            return self ._claude 
        elif self .provider =="koboldai":
            return self ._koboldai 
        elif self .provider =="llamacpp":
            return self ._llamacpp 
        elif self .provider in self .OPENAI_COMPAT :
            return self ._openai_compat .get (self .provider )
        return self ._gemini 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        inst =self ._provider_instance ()
        async for token in inst .stream (messages ):
            yield token 

    async def generate (self ,messages :list )->str :
        inst =self ._provider_instance ()
        return await inst .generate (messages )

    async def get_embedding (self ,text :str )->List [float ]:
        if self .provider =="gemini":
            return await self ._gemini .get_embedding (text )
        return await self ._ollama .get_embedding (text )

    async def fetch_ollama_models (self )->List [str ]:
        return await self ._ollama .fetch_models ()

    async def fetch_gemini_models (self )->List [str ]:
        return await self ._gemini .fetch_models ()

    async def fetch_openai_compat_models (self ,provider :str )->List [str ]:
        inst =self ._openai_compat .get (provider )
        if inst :
            return await inst .fetch_models ()
        return []

    async def close (self ):
        await self ._gemini .close ()
        await self ._ollama .close ()
        await self ._claude .close ()
        await self ._llamacpp .close ()
        await self ._koboldai .close ()
        for p in self ._openai_compat .values ():
            await p .close ()
