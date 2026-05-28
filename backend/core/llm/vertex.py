"""GCP Vertex AI provider (Gemini via Vertex AI)."""
import json 
import logging 
from typing import AsyncIterator ,List ,Dict ,Any 

import httpx 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class VertexProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._model =""
        self ._project_id =""
        self ._region ="us-central1"
        self ._service_account_json =""
        self ._client =None 
        self ._load_config ()

    def _load_config (self ):
        if self .settings :
            self ._model =self .settings .get ("provider.gcp.model","")
            self ._project_id =self .settings .get ("provider.gcp.project_id","")
            self ._region =self .settings .get ("provider.gcp.region","us-central1")
            self ._service_account_json =self .settings .get ("provider.gcp.service_account_json","")

    def name (self )->str :
        return "gcp"

    def supports_native_tools (self )->bool :
        return bool (self ._model )

    async def _ensure_client (self ):
        if self ._client is not None :
            return self ._client 
        self ._client =httpx .AsyncClient (timeout =httpx .Timeout (120.0 ,connect =10.0 ))
        return self ._client 

    async def _get_headers (self )->dict :
        import google .auth 
        from google .auth .transport .requests import Request 

        if self ._service_account_json :
            import google .auth .transport .requests 
            from google .oauth2 import service_account 

            creds =service_account .Credentials .from_service_account_info (
            json .loads (self ._service_account_json ),
            scopes =["https://www.googleapis.com/auth/cloud-platform"],
            )
        else :
            creds ,_ =google .auth .default (
            scopes =["https://www.googleapis.com/auth/cloud-platform"]
            )

        creds .refresh (Request ())
        token =creds .token 
        return {
        "Authorization":f"Bearer {token }",
        "Content-Type":"application/json",
        }

    def _build_url (self ,action :str ="streamGenerateContent")->str :
        project =self ._project_id 
        if not project :
            raise RuntimeError ("[Error: GCP Vertex AI project_id not set. Go to Settings > Providers.]")
        model =self ._model 
        return (f"https://{self ._region }-aiplatform.googleapis.com/v1/"
        f"projects/{project }/locations/{self ._region }/publishers/google/models/{model }:{action }")

    def _convert_messages (self ,messages :list )->list :
        vertex_contents =[]
        for m in messages :
            role =m .get ("role","user")
            content =m .get ("content","")
            if isinstance (content ,str ):
                if role =="assistant":
                    vertex_contents .append ({"role":"model","parts":[{"text":content }]})
                else :
                    vertex_contents .append ({"role":"user","parts":[{"text":content }]})
            elif isinstance (content ,list ):
                parts =[]
                for c in content :
                    if isinstance (c ,dict ):
                        if "text"in c :
                            parts .append ({"text":c ["text"]})
                        elif "image_url"in c :
                            parts .append ({"inlineData":{"mimeType":"image/jpeg","data":c ["image_url"].get ("url","")}})
                    else :
                        parts .append ({"text":str (c )})
                vertex_contents .append ({"role":"user"if role =="user"else "model","parts":parts })
        return vertex_contents 

    def _convert_tools (self ,tools :List [Dict [str ,Any ]])->list :
        vertex_tools =[]
        for t in tools :
            vertex_tools .append ({
            "functionDeclarations":[{
            "name":t ["name"],
            "description":t .get ("description",""),
            "parameters":t .get ("parameters",{"type":"object","properties":{}}),
            }]
            })
        return vertex_tools 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        async for item in self .stream_with_tools (messages ,[]):
            if isinstance (item ,str ):
                yield item 

    async def stream_with_tools (
    self ,messages :list ,tools :List [Dict [str ,Any ]]
    )->AsyncIterator :
        if not self ._model :
            yield "[Error: GCP Vertex AI model not set. Go to Settings > Providers.]"
            return 
        if not self ._project_id :
            yield "[Error: GCP Vertex AI project_id not set. Go to Settings > Providers.]"
            return 

        max_tokens =self .get_max_output_tokens ()

        try :
            client =await self ._ensure_client ()
            headers =await self ._get_headers ()
            url =self ._build_url ("streamGenerateContent")

            body ={
            "contents":self ._convert_messages (messages ),
            "generationConfig":{
            "maxOutputTokens":max_tokens ,
            "temperature":self .temperature ,
            },
            }
            if tools :
                body ["tools"]=self ._convert_tools (tools )

            async with client .stream ("POST",url ,json =body ,headers =headers )as response :
                if response .status_code !=200 :
                    err =await response .aread ()
                    raise RuntimeError (_format_error (response .status_code ,err .decode ()))

                async for line in response .aiter_lines ():
                    if not line .strip ():
                        continue 
                    try :
                        data =json .loads (line )
                    except json .JSONDecodeError :
                        continue 

                    candidates =data .get ("candidates",[])
                    for c in candidates :
                        content =c .get ("content",{})
                        parts =content .get ("parts",[])
                        for part in parts :
                            text =part .get ("text","")
                            if text :
                                yield text 

                            fc =part .get ("functionCall",{})
                            if fc :
                                yield {
                                "type":"tool_use",
                                "id":fc .get ("name","unknown"),
                                "name":fc .get ("name",""),
                                "arguments":fc .get ("args",{}),
                                }

                        finish_reason =c .get ("finishReason","")
                        if finish_reason =="STOP":
                            return 

        except RuntimeError :
            raise 
        except Exception as e :
            logger .error (f"GCP Vertex AI stream error: {e }")
            yield f"[Error connecting to GCP Vertex AI: {e }]"

    async def generate (self ,messages :list )->str :
        if not self ._model :
            return "[Error: GCP Vertex AI model not set]"
        if not self ._project_id :
            return "[Error: GCP Vertex AI project_id not set]"

        max_tokens =self .get_max_output_tokens ()

        try :
            client =await self ._ensure_client ()
            headers =await self ._get_headers ()
            url =self ._build_url ("generateContent")

            body ={
            "contents":self ._convert_messages (messages ),
            "generationConfig":{
            "maxOutputTokens":max_tokens ,
            "temperature":self .temperature ,
            },
            }

            response =await client .post (url ,json =body ,headers =headers )
            if response .status_code ==200 :
                data =response .json ()
                candidates =data .get ("candidates",[])
                for c in candidates :
                    parts =c .get ("content",{}).get ("parts",[])
                    texts =[p ["text"]for p in parts if "text"in p ]
                    if texts :
                        return "".join (texts )
            else :
                return _format_error (response .status_code ,response .text )
        except Exception as e :
            logger .error (f"GCP Vertex AI generate error: {e }")
            return f"Error: {e }"
        return ""

    async def fetch_models (self )->List [str ]:
        if not self ._project_id :
            return []
        try :
            client =await self ._ensure_client ()
            headers =await self ._get_headers ()
            url =(f"https://{self ._region }-aiplatform.googleapis.com/v1/"
            f"projects/{self ._project_id }/locations/{self ._region }/publishers/google/models")
            response =await client .get (url ,headers =headers ,timeout =10.0 )
            if response .status_code ==200 :
                models =response .json ().get ("models",[])
                return sorted ([m ["name"].rsplit ("/",1 )[-1 ]for m in models ])
        except Exception as e :
            logger .error (f"GCP Vertex AI models fetch error: {e }")
        return []

    async def close (self ):
        if self ._client :
            await self ._client .aclose ()
            self ._client =None 


def _format_error (status_code :int ,body :str )->str :
    import re as _re 
    message =body .strip ()
    if not message :
        return f"API Error {status_code }"
    try :
        data =json .loads (body )
        if isinstance (data ,dict )and "error"in data :
            err =data ["error"]
            if isinstance (err ,dict ):
                msg =err .get ("message",str (err ))
                code =err .get ("code",status_code )
                try :
                    code =int (code )
                except (ValueError ,TypeError ):
                    pass 
                first_sentence =_re .split (r'(?<=[.!?])\s+',msg .strip ())[0 ]
                if code ==429 :
                    return f"API rate limit exceeded. {first_sentence }."
                return first_sentence 
            return str (err )
    except (json .JSONDecodeError ,IndexError ,KeyError ,TypeError ):
        pass 
    if len (message )>200 :
        message =message [:200 ].rsplit (' ',1 )[0 ]+'...'
    return message 
