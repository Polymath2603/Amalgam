"""Anthropic Claude provider via Messages API."""
import json 
import logging 
from typing import AsyncIterator ,List 

import httpx 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class ClaudeProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._api_key =""
        self ._model ="claude-sonnet-4-20250514"
        self ._base_url ="https://api.anthropic.com/v1"
        self ._load_config ()
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))

    def _load_config (self ):
        if self .settings :
            self ._api_key =self .settings .get ("provider.claude.api_key","")
            self ._model =self .settings .get ("provider.claude.model","claude-sonnet-4-20250514")
            self ._base_url =self .settings .get ("provider.claude.base_url","https://api.anthropic.com/v1")

    def _build_messages (self ,messages :list )->list :
        result =[]
        for m in messages :
            role =m .get ("role","user")
            content =m .get ("content","")
            if role =="system":
                continue 
            result .append ({"role":role ,"content":content })
        return result 

    def _get_system (self ,messages :list )->str :
        for m in messages :
            if m .get ("role")=="system":
                return m .get ("content","")
        return ""

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        if not self ._api_key :
            yield "[Error: Claude API key not set. Go to Settings > Providers.]"
            return 

        url =f"{self ._base_url .rstrip ('/')}/messages"
        system =self ._get_system (messages )
        body ={
        "model":self ._model ,
        "messages":self ._build_messages (messages ),
        "stream":True ,
        "max_tokens":2048 ,
        }
        if system :
            body ["system"]=system 

        headers ={
        "x-api-key":self ._api_key ,
        "anthropic-version":"2023-06-01",
        "Content-Type":"application/json",
        }
        try :
            async with self ._client .stream ("POST",url ,json =body ,headers =headers )as response :
                if response .status_code !=200 :
                    err =await response .aread ()
                    yield self ._format_error (response .status_code ,err .decode ())
                    return 
                async for line in response .aiter_lines ():
                    if line .startswith ("data: "):
                        json_str =line [6 :].strip ()
                        if json_str =="[DONE]":
                            return 
                        try :
                            data =json .loads (json_str )
                            if data .get ("type")=="content_block_delta":
                                delta =data .get ("delta",{})
                                text =delta .get ("text","")
                                if text :
                                    yield text 
                        except json .JSONDecodeError :
                            pass 
        except Exception as e :
            logger .error (f"Claude stream error: {e }")
            yield f"[Error connecting to Claude: {e }]"

    async def generate (self ,messages :list )->str :
        if not self ._api_key :
            return "[Error: Claude API key not set]"
        url =f"{self ._base_url .rstrip ('/')}/messages"
        system =self ._get_system (messages )
        body ={
        "model":self ._model ,
        "messages":self ._build_messages (messages ),
        "max_tokens":2048 ,
        }
        if system :
            body ["system"]=system 
        headers ={
        "x-api-key":self ._api_key ,
        "anthropic-version":"2023-06-01",
        "Content-Type":"application/json",
        }
        try :
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code ==200 :
                data =response .json ()
                content =data .get ("content",[])
                return "".join (block .get ("text","")for block in content if block .get ("type")=="text")
            else :
                return self ._format_error (response .status_code ,response .text )
        except Exception as e :
            logger .error (f"Claude generate error: {e }")
            return f"Error: {e }"

    async def close (self ):
        await self ._client .aclose ()

    def _format_error (self ,status_code :int ,body :str )->str :
        try :
            data =json .loads (body )
            err =data .get ("error",{})
            if isinstance (err ,dict ):
                return err .get ("message",str (err ))
            return str (err )
        except (json .JSONDecodeError ,KeyError ,TypeError ):
            pass 
        return body [:200 ]if body else f"API Error {status_code }"
