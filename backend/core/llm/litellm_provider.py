"""
LiteLLM-based provider — unified wrapper for all LLM backends.

Replaces per-provider classes (gemini, claude, ollama, openai_compat, etc.)
with a single class that delegates to litellm.acompletion().
"""

import json 
import logging 
from typing import AsyncIterator ,List ,Dict ,Any ,Optional 

import litellm 
from litellm import acompletion ,aembedding 

logger =logging .getLogger (__name__ )


litellm .suppress_debug_info =True 


PROVIDER_PREFIX ={
"gemini":"gemini",
"openrouter":"openrouter",
"groq":"groq",
"deepseek":"deepseek",
"mistral":"mistral",
"together":"together_ai",
"chatgpt":"openai",
"azure-openai":"azure",
"alibaba":"dashscope",
"huggingface":"huggingface",
"zai":"zai",
"siliconflow":"openai",
"claude":"anthropic",
"ollama":"ollama",
"llamacpp":"openai",
"koboldai":"openai",
"aws":"bedrock",
"gcp":"vertex_ai",
}


TOOL_CAPABLE ={
"gemini","openrouter","groq","deepseek","mistral","together",
"chatgpt","azure-openai","alibaba","huggingface","zai","siliconflow",
"claude","aws","gcp",
}


CONTEXT_LIMITS ={
"groq":3000 ,
"llamacpp":4096 ,
"koboldai":4096 ,
}


OUTPUT_LIMITS ={
"groq":1024 ,
"llamacpp":2048 ,
"koboldai":2048 ,
}


EMBEDDING_CAPABLE ={
"gemini","ollama","openai","deepseek","mistral",
"together","groq","chatgpt","azure-openai",
"openrouter","alibaba","huggingface","aws","gcp",
}


EMBEDDING_MODEL_DEFAULTS ={
"gemini":"gemini/text-embedding-004",
"ollama":"nomic-embed-text",
"openai":"openai/text-embedding-3-small",
"chatgpt":"openai/text-embedding-3-small",
"azure-openai":"azure/text-embedding-3-small",
"deepseek":"openai/text-embedding-3-small",
"mistral":"mistral/mistral-embed",
"together":"together_ai/nomic-ai/nomic-embed-text-v1.5",
"groq":"openai/text-embedding-3-small",
"openrouter":"openai/text-embedding-3-small",
"alibaba":"openai/text-embedding-3-small",
"huggingface":"openai/text-embedding-3-small",
"aws":"bedrock/amazon.titan-embed-text-v2:0",
"gcp":"vertex_ai/textembedding-gecko",
}


class LiteLLMProvider :
    """Unified LLM provider using LiteLLM."""

    def __init__ (self ,settings =None ):
        self ._settings =settings 
        self ._provider ="gemini"
        self ._reload ()

    def _reload (self ):
        if self ._settings :
            self ._provider =self ._settings .get ("provider.active","gemini")

    def reload_settings (self ):
        if self ._settings :
            self ._settings .load ()
        self ._reload ()

    def _get_model_config (self )->tuple [str ,dict ]:
        """Build LiteLLM model string and kwargs from settings.

        Returns:
            (model_string, extra_kwargs) for litellm.acompletion()
        """
        provider =self ._provider 
        cfg ={}
        if self ._settings :
            cfg =self ._settings .get (f"provider.{provider }",{})

        if not cfg :
            cfg ={}

        model_name =cfg .get ("model","")
        api_key =cfg .get ("api_key","")
        base_url =cfg .get ("base_url","")


        prefix =PROVIDER_PREFIX .get (provider ,provider )
        if provider in ("llamacpp","koboldai","siliconflow"):

            model =model_name 
        elif provider =="ollama":
            model =f"ollama/{model_name }"
        else :
            model =f"{prefix }/{model_name }"if model_name else prefix 


        kwargs ={}
        if api_key :
            kwargs ["api_key"]=api_key 
        if base_url :
            kwargs ["api_base"]=base_url .rstrip ("/")


        if provider =="aws":
            kwargs ["aws_access_key_id"]=cfg .get ("access_key","")
            kwargs ["aws_secret_access_key"]=cfg .get ("secret_key","")
            kwargs ["aws_region_name"]=cfg .get ("region","us-east-1")
        elif provider =="gcp":

            sa_json =cfg .get ("service_account_json","")
            if sa_json :
                kwargs ["vertex_credentials"]=sa_json 
            kwargs ["vertex_project"]=cfg .get ("project_id","")
            kwargs ["vertex_location"]=cfg .get ("region","us-central1")

        return model ,kwargs 

    def _get_temperature (self ,override :float =None )->float :
        if override is not None :
            return float (override )
        if self ._settings :
            return float (self ._settings .get ("llm.temperature",0.7 ))
        return 0.7 

    def supports_native_tools (self )->bool :
        return self ._provider in TOOL_CAPABLE 

    def get_max_output_tokens (self )->int :
        if self ._provider in OUTPUT_LIMITS :
            return OUTPUT_LIMITS [self ._provider ]
        if self ._settings :
            return int (self ._settings .get ("llm.max_tokens",2048 ))
        return 2048 

    def get_context_token_limit (self )->int :
        if self ._provider in CONTEXT_LIMITS :
            return CONTEXT_LIMITS [self ._provider ]
        if self ._settings :
            return int (self ._settings .get ("llm.context_token_limit",8192 ))
        return 8192 

    async def stream (self ,messages :list ,temperature :float =None )->AsyncIterator [str ]:
        """Stream text-only completion."""
        model ,kwargs =self ._get_model_config ()
        temp =self ._get_temperature (temperature )
        max_tokens =self .get_max_output_tokens ()

        try :
            response =await acompletion (
            model =model ,messages =messages ,stream =True ,
            temperature =temp ,max_tokens =max_tokens ,**kwargs 
            )
            async for chunk in response :
                delta =chunk .choices [0 ].delta if chunk .choices else None 
                if delta and delta .content :
                    yield delta .content 
        except Exception as e :
            logger .error (f"LiteLLM stream error ({self ._provider }): {e }")
            yield f"[Error: {e }]"

    async def stream_with_tools (
    self ,messages :list ,tools :List [Dict [str ,Any ]],temperature :float =None 
    )->AsyncIterator :
        """Stream completion with native tool calling.

        Yields str (text tokens) and dict (tool_use calls).
        """
        model ,kwargs =self ._get_model_config ()
        temp =self ._get_temperature (temperature )
        max_tokens =self .get_max_output_tokens ()


        pending_tool_calls :Dict [int ,dict ]={}

        try :
            response =await acompletion (
            model =model ,messages =messages ,stream =True ,
            tools =tools ,tool_choice ="auto",
            temperature =temp ,max_tokens =max_tokens ,**kwargs 
            )
            async for chunk in response :
                delta =chunk .choices [0 ].delta if chunk .choices else None 
                if not delta :
                    continue 


                if delta .content :
                    yield delta .content 


                if delta .tool_calls :
                    for tc in delta .tool_calls :
                        idx =tc .index or 0 
                        if idx not in pending_tool_calls :
                            pending_tool_calls [idx ]={"id":"","name":"","arguments":""}
                        pt =pending_tool_calls [idx ]
                        if tc .id :
                            pt ["id"]=tc .id 
                        if tc .function and tc .function .name :
                            pt ["name"]=tc .function .name 
                        if tc .function and tc .function .arguments :
                            pt ["arguments"]+=tc .function .arguments 


                finish =chunk .choices [0 ].finish_reason if chunk .choices else None 
                if finish =="tool_calls"and pending_tool_calls :
                    for idx in sorted (pending_tool_calls .keys ()):
                        pt =pending_tool_calls [idx ]
                        if pt ["id"]and pt ["name"]:
                            try :
                                args =json .loads (pt ["arguments"])if pt ["arguments"]else {}
                            except json .JSONDecodeError :
                                args ={}
                            yield {
                            "type":"tool_use",
                            "id":pt ["id"],
                            "name":pt ["name"],
                            "arguments":args ,
                            }
                    pending_tool_calls .clear ()

        except Exception as e :
            logger .error (f"LiteLLM stream_with_tools error ({self ._provider }): {e }")
            yield f"[Error: {e }]"

    async def generate (self ,messages :list ,temperature :float =None )->str :
        """Non-streaming completion."""
        model ,kwargs =self ._get_model_config ()
        temp =self ._get_temperature (temperature )
        max_tokens =self .get_max_output_tokens ()

        try :
            response =await acompletion (
            model =model ,messages =messages ,
            temperature =temp ,max_tokens =max_tokens ,**kwargs 
            )
            return response .choices [0 ].message .content or ""
        except Exception as e :
            logger .error (f"LiteLLM generate error ({self ._provider }): {e }")
            return f"[Error: {e }]"

    async def get_embedding (self ,text :str )->List [float ]:
        """Generate embedding vector."""
        if self ._provider not in EMBEDDING_CAPABLE :
            return []

        model ,kwargs =self ._get_model_config ()


        embed_model =None 
        if self ._settings :
            embed_model =self ._settings .get ("memory.embedding_model","")

        if not embed_model :

            if self ._provider =="ollama":
                ollama_model ="nomic-embed-text"
                if self ._settings :
                    ollama_model =self ._settings .get ("provider.ollama.model",ollama_model )

                    if "embed"not in ollama_model .lower ():
                        ollama_model ="nomic-embed-text"
                embed_model =f"ollama/{ollama_model }"
            else :
                embed_model =EMBEDDING_MODEL_DEFAULTS .get (self ._provider ,"")

        if not embed_model :
            return []

        try :
            response =await aembedding (model =embed_model ,input =[text ],**kwargs )
            return response .data [0 ].embedding 
        except Exception as e :
            logger .error (f"LiteLLM embedding error ({self ._provider }, model={embed_model }): {e }")
            return []

    async def close (self ):
        """No-op — LiteLLM manages its own HTTP clients."""
        pass 
