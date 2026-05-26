from typing import AsyncIterator ,List ,Dict ,Any 


class LLMProvider :
    def __init__ (self ,settings ):
        self .settings =settings 
        self .temperature =0.7 

    def supports_native_tools (self )->bool :
        """Does this provider support native tool/function calling?"""
        return False 

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
