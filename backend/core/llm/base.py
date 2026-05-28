from typing import AsyncIterator ,List ,Dict ,Any 


class LLMProvider :
    def __init__ (self ,settings ):
        self .settings =settings 
        self .temperature =0.7 

    def supports_native_tools (self )->bool :
        """Does this provider support native tool/function calling?"""
        return False 

    def get_max_output_tokens (self )->int :
        """Get the maximum completion tokens to request based on provider limits."""
        return self .settings .get ("llm.max_tokens",2048 )if self .settings else 2048 

    def get_context_token_limit (self )->int :
        """Get the max context window size (prompt) based on provider constraints."""
        return self .settings .get ("llm.context_token_limit",8192 )if self .settings else 8192 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        raise NotImplementedError 

    async def stream_with_tools (
    self ,messages :list ,tools :List [Dict [str ,Any ]]
    )->AsyncIterator :
        """Stream response with native tool calling support.
        
        Yields either strings (text tokens) or dicts with tool call info.
        Default implementation: no native tools, yields text only.
        """
        async for token in self .stream (messages ):
            yield token 

    async def generate (self ,messages :list )->str :
        raise NotImplementedError 

    async def get_embedding (self ,text :str )->List [float ]:
        return []

    async def fetch_models (self )->List [str ]:
        return []
