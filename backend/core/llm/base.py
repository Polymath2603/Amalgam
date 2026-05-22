from typing import AsyncIterator ,List 


class LLMProvider :
    def __init__ (self ,settings ):
        self .settings =settings 
        self .temperature =0.7 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        raise NotImplementedError 

    async def generate (self ,messages :list )->str :
        raise NotImplementedError 

    async def get_embedding (self ,text :str )->List [float ]:
        return []

    async def fetch_models (self )->List [str ]:
        return []
