"""
LLM Router — routes to Ollama or Gemini based on settings.
Supports streaming, non-streaming generate, and embeddings.
Uses OpenAI-compatible endpoints where possible.
"""
import json 
import httpx 
import logging 
from typing import AsyncIterator 

logger =logging .getLogger (__name__ )


class LLMRouter :
    def __init__ (self ,settings =None ):
        self .settings =settings 
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))
        self ._load_config ()


    OPENAI_COMPAT ={"openrouter","zai","siliconflow","groq","chatgpt"}

    def _load_config (self ):
        """Load provider configuration from settings."""
        if self .settings :
            self .provider =self .settings .get ("provider.active","gemini")


            self ._gemini_key =self .settings .get ("provider.gemini.api_key","")
            self ._gemini_model =self .settings .get ("provider.gemini.model","gemini-2.0-flash")
            self ._gemini_base_url =self .settings .get ("provider.gemini.base_url",
            "https://generativelanguage.googleapis.com/v1beta")


            self ._ollama_url =self .settings .get ("provider.ollama.base_url","http://localhost:11434")
            self ._ollama_model =self .settings .get ("provider.ollama.model","")


            for p in self .OPENAI_COMPAT :
                setattr (self ,f"_{p }_key",self .settings .get (f"provider.{p }.api_key",""))
                setattr (self ,f"_{p }_model",self .settings .get (f"provider.{p }.model",""))
                setattr (self ,f"_{p }_base_url",self .settings .get (f"provider.{p }.base_url",""))
        else :

            self .provider ="gemini"
            self ._gemini_key =""
            self ._gemini_model ="gemini-2.0-flash"
            self ._gemini_base_url ="https://generativelanguage.googleapis.com/v1beta"
            self ._ollama_url ="http://localhost:11434"
            self ._ollama_model =""
            for p in self .OPENAI_COMPAT :
                setattr (self ,f"_{p }_key","")
                setattr (self ,f"_{p }_model","")
                setattr (self ,f"_{p }_base_url","")

    def reload_settings (self ):
        """Call after settings change to pick up new provider/model."""
        if self .settings :
            self .settings .load ()
        self ._load_config ()



    async def stream (self ,messages :list )->AsyncIterator [str ]:
        """Stream tokens from the active provider.
        Accepts a list of message dicts with 'role' and 'content'.
        """
        if self .provider =="gemini":
            async for token in self ._stream_gemini (messages ):
                yield token 
        elif self .provider in self .OPENAI_COMPAT :
            async for token in self ._stream_openai_compat (self .provider ,messages ):
                yield token 
        else :
            async for token in self ._stream_ollama (messages ):
                yield token 

    async def _stream_ollama (self ,messages :list )->AsyncIterator [str ]:
        try :
            async with self ._client .stream (
            "POST",
            f"{self ._ollama_url }/api/chat",
            json ={"model":self ._ollama_model ,"messages":messages ,"stream":True },
            )as response :
                if response .status_code !=200 :
                    yield f"Error: Ollama returned {response .status_code }"
                    return 
                async for line in response .aiter_lines ():
                    if line :
                        try :
                            data =json .loads (line )
                            msg =data .get ("message",{})
                            if "content"in msg :
                                yield msg ["content"]
                        except json .JSONDecodeError :
                            pass 
        except Exception as e :
            logger .error (f"Ollama stream error: {e }")
            yield f"[Error connecting to Ollama: {e }]"

    async def _stream_gemini (self ,messages :list )->AsyncIterator [str ]:
        if not self ._gemini_key :
            yield "[Error: Gemini API key not set. Go to Settings > Providers.]"
            return 


        url =f"{self ._gemini_base_url }/openai/chat/completions"
        headers ={
        "Authorization":f"Bearer {self ._gemini_key }",
        "Content-Type":"application/json",
        }
        body ={
        "model":self ._gemini_model ,
        "messages":messages ,
        "stream":True ,
        "temperature":0.7 ,
        "max_tokens":2048 
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
                            choices =data .get ("choices",[])
                            for c in choices :
                                delta =c .get ("delta",{})
                                content =delta .get ("content","")
                                if content :
                                    yield content 
                        except json .JSONDecodeError :
                            pass 
        except Exception as e :
            logger .error (f"Gemini stream error: {e }")
            yield f"[Error connecting to Gemini: {e }]"

    async def _stream_openai_compat (self ,provider :str ,messages :list )->AsyncIterator [str ]:
        """Stream from any OpenAI-compatible provider (OpenRouter, Z.AI, SiliconFlow)."""
        api_key =getattr (self ,f"_{provider }_key","")
        model =getattr (self ,f"_{provider }_model","")
        base_url =getattr (self ,f"_{provider }_base_url","")

        if not api_key :
            yield f"[Error: {provider } API key not set. Go to Settings > Providers.]"
            return 

        url =f"{base_url .rstrip ('/')}/chat/completions"
        headers ={
        "Authorization":f"Bearer {api_key }",
        "Content-Type":"application/json",
        }
        body ={
        "model":model ,
        "messages":messages ,
        "stream":True ,
        "temperature":0.7 ,
        "max_tokens":2048 
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
                            choices =data .get ("choices",[])
                            for c in choices :
                                delta =c .get ("delta",{})
                                content =delta .get ("content","")
                                if content :
                                    yield content 
                        except json .JSONDecodeError :
                            pass 
        except Exception as e :
            logger .error (f"{provider } stream error: {e }")
            yield f"[Error connecting to {provider }: {e }]"



    async def generate (self ,messages :list )->str :
        """Generate a response from the active provider."""
        if self .provider =="gemini":
            return await self ._generate_gemini (messages )
        elif self .provider in self .OPENAI_COMPAT :
            return await self ._generate_openai_compat (self .provider ,messages )
        return await self ._generate_ollama (messages )

    async def _generate_ollama (self ,messages :list )->str :
        try :
            response =await self ._client .post (
            f"{self ._ollama_url }/api/chat",
            json ={"model":self ._ollama_model ,"messages":messages ,"stream":False },
            )
            if response .status_code ==200 :
                msg =response .json ().get ("message",{})
                return msg .get ("content","")
        except Exception as e :
            logger .error (f"Ollama generate error: {e }")
            return f"Error: {e }"
        return ""

    async def _generate_gemini (self ,messages :list )->str :
        if not self ._gemini_key :
            return "[Error: Gemini API key not set]"

        url =f"{self ._gemini_base_url }/openai/chat/completions"
        headers ={
        "Authorization":f"Bearer {self ._gemini_key }",
        "Content-Type":"application/json",
        }
        body ={
        "model":self ._gemini_model ,
        "messages":messages ,
        "temperature":0.7 ,
        "max_tokens":2048 
        }

        try :
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code ==200 :
                data =response .json ()
                choices =data .get ("choices",[])
                if choices :
                    return choices [0 ].get ("message",{}).get ("content","")
            else :
                return self ._format_error (response .status_code ,response .text )
        except Exception as e :
            logger .error (f"Gemini generate error: {e }")
            return f"Error: {e }"
        return ""

    async def _generate_openai_compat (self ,provider :str ,messages :list )->str :
        """Non-streaming generate for OpenAI-compatible providers."""
        api_key =getattr (self ,f"_{provider }_key","")
        model =getattr (self ,f"_{provider }_model","")
        base_url =getattr (self ,f"_{provider }_base_url","")

        if not api_key :
            return f"[Error: {provider } API key not set]"

        url =f"{base_url .rstrip ('/')}/chat/completions"
        headers ={
        "Authorization":f"Bearer {api_key }",
        "Content-Type":"application/json",
        }
        body ={
        "model":model ,
        "messages":messages ,
        "temperature":0.7 ,
        "max_tokens":2048 
        }

        try :
            response =await self ._client .post (url ,json =body ,headers =headers )
            if response .status_code ==200 :
                data =response .json ()
                choices =data .get ("choices",[])
                if choices :
                    return choices [0 ].get ("message",{}).get ("content","")
            else :
                return self ._format_error (response .status_code ,response .text )
        except Exception as e :
            logger .error (f"{provider } generate error: {e }")
            return f"Error: {e }"
        return ""



    async def get_embedding (self ,text :str )->list :
        if self .provider =="gemini":
            return await self ._embed_gemini (text )
        return await self ._embed_ollama (text )

    async def _embed_ollama (self ,text :str )->list :
        try :
            response =await self ._client .post (
            f"{self ._ollama_url }/api/embeddings",
            json ={"model":self ._ollama_model ,"prompt":text },
            )
            if response .status_code ==200 :
                return response .json ().get ("embedding",[])
        except Exception :
            pass 
        return []

    async def _embed_gemini (self ,text :str )->list :
        if not self ._gemini_key :
            return []
        url =f"{self ._gemini_base_url }/models/text-embedding-004:embedContent?key={self ._gemini_key }"
        body ={"content":{"parts":[{"text":text }]}}
        try :
            response =await self ._client .post (url ,json =body )
            if response .status_code ==200 :
                return response .json ().get ("embedding",{}).get ("values",[])
        except Exception :
            pass 
        return []



    async def fetch_ollama_models (self )->list :
        try :
            response =await self ._client .get (f"{self ._ollama_url }/api/tags",timeout =5.0 )
            if response .status_code ==200 :
                return [m ["name"]for m in response .json ().get ("models",[])]
        except Exception :
            pass 
        return []

    async def fetch_gemini_models (self )->list :
        """Fetch available Gemini models using the native API."""
        if not self ._gemini_key :
            logger .warning ("Gemini API key not set — cannot fetch models")
            return []
        try :
            url =f"https://generativelanguage.googleapis.com/v1beta/models?key={self ._gemini_key }"
            logger .info (f"Fetching Gemini models from {url [:60 ]}...")
            response =await self ._client .get (url ,timeout =10.0 )
            if response .status_code ==200 :
                data =response .json ()
                models =data .get ("models",[])
                result =[
                m ["name"].replace ("models/","")
                for m in models 
                if "generateContent"in m .get ("supportedGenerationMethods",[])
                ]
                logger .info (f"Found {len (result )} Gemini models")
                return result 
            else :
                body =response .text [:300 ]
                logger .error (f"Gemini models fetch returned {response .status_code }: {body }")
        except Exception as e :
            logger .error (f"Gemini models fetch error: {e }")
        return []

    async def fetch_openai_compat_models (self ,provider :str )->list :
        """Fetch available models from an OpenAI-compatible /v1/models endpoint."""
        api_key =getattr (self ,f"_{provider }_key","")
        base_url =getattr (self ,f"_{provider }_base_url","")
        if not api_key or not base_url :
            logger .warning (f"{provider }: missing API key or base URL")
            return []
        try :
            url =f"{base_url .rstrip ('/')}/models"
            headers ={"Authorization":f"Bearer {api_key }"}
            logger .info (f"Fetching {provider } models from {url [:60 ]}...")
            response =await self ._client .get (url ,headers =headers ,timeout =10.0 )
            if response .status_code ==200 :
                data =response .json ()
                models =data .get ("data",[])
                result =[m ["id"]for m in models if "id"in m ]
                result .sort ()
                logger .info (f"Found {len (result )} {provider } models")
                return result 
            else :
                body =response .text [:300 ]
                logger .error (f"{provider } models fetch returned {response .status_code }: {body }")
        except Exception as e :
            logger .error (f"{provider } models fetch error: {e }")
        return []



    @staticmethod 
    def _format_error (status_code :int ,body :str )->str :
        """Parse API error JSON into a human-readable message."""
        message =body .strip ()
        if not message :
            return f"API Error {status_code }"


        try :
            data =json .loads (body )
            if isinstance (data ,list )and data :
                data =data [0 ]
            if isinstance (data ,dict )and "error"in data :
                err =data ["error"]
                if isinstance (err ,dict ):
                    msg =err .get ("message",str (err ))
                    code =err .get ("code",status_code )
                    try :
                        code =int (code )
                    except (ValueError ,TypeError ):
                        pass 
                    if code ==429 :
                        return f"Quota exceeded. {msg }"
                    return msg 
                return str (err )
        except (json .JSONDecodeError ,IndexError ,KeyError ,TypeError ):
            pass 



        if len (message )>200 :
            message =message [:200 ].rsplit (' ',1 )[0 ]+'...'
        return message 



    async def close (self ):
        await self ._client .aclose ()
