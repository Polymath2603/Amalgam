"""AWS Bedrock provider using the Converse API."""
import json 
import logging 
from typing import AsyncIterator ,List ,Dict ,Any 

from .base import LLMProvider 

logger =logging .getLogger (__name__ )


class BedrockProvider (LLMProvider ):
    def __init__ (self ,settings ):
        super ().__init__ (settings )
        self ._model =""
        self ._region ="us-east-1"
        self ._access_key =""
        self ._secret_key =""
        self ._client =None 
        self ._load_config ()

    def _load_config (self ):
        if self .settings :
            self ._model =self .settings .get ("provider.aws.model","")
            self ._region =self .settings .get ("provider.aws.region","us-east-1")
            self ._access_key =self .settings .get ("provider.aws.access_key","")
            self ._secret_key =self .settings .get ("provider.aws.secret_key","")

    def _get_client (self ):
        if self ._client is not None :
            return self ._client 
        import boto3 
        from botocore .config import Config as BotoConfig 

        kwargs ={"region_name":self ._region ,"config":BotoConfig (read_timeout =120 ,connect_timeout =10 )}
        if self ._access_key and self ._secret_key :
            kwargs ["aws_access_key_id"]=self ._access_key 
            kwargs ["aws_secret_access_key"]=self ._secret_key 
        session =boto3 .Session (**kwargs )
        self ._client =session .client ("bedrock-runtime")
        return self ._client 

    def name (self )->str :
        return "aws"

    def supports_native_tools (self )->bool :
        return bool (self ._model )

    def _convert_messages (self ,messages :list )->list :
        result =[]
        for m in messages :
            role =m .get ("role","user")
            content =m .get ("content","")
            if isinstance (content ,str ):
                result .append ({"role":role ,"content":[{"text":content }]})
            elif isinstance (content ,list ):
                result .append ({"role":role ,"content":content })
        return result 

    def _convert_tools (self ,tools :List [Dict [str ,Any ]])->list :
        bedrock_tools =[]
        for t in tools :
            bedrock_tools .append ({
            "toolSpec":{
            "name":t ["name"],
            "description":t .get ("description",""),
            "inputSchema":{"json":t .get ("parameters",{"type":"object","properties":{}})},
            }
            })
        return bedrock_tools 

    async def stream (self ,messages :list )->AsyncIterator [str ]:
        async for item in self .stream_with_tools (messages ,[]):
            if isinstance (item ,str ):
                yield item 

    async def stream_with_tools (
    self ,messages :list ,tools :List [Dict [str ,Any ]]
    )->AsyncIterator :
        if not self ._model :
            yield "[Error: AWS Bedrock model not set. Go to Settings > Providers.]"
            return 

        max_tokens =self .get_max_output_tokens ()
        inference_config ={
        "maxTokens":max_tokens ,
        "temperature":self .temperature ,
        }

        body ={
        "modelId":self ._model ,
        "messages":self ._convert_messages (messages ),
        "inferenceConfig":inference_config ,
        }
        if tools :
            body ["toolConfig"]={"tools":self ._convert_tools (tools )}

        try :
            client =self ._get_client ()
            response =client .converse_stream (**body )
            stream =response .get ("stream",[])
            pending_tool_calls :Dict [int ,dict ]={}

            for event in stream :
                if "contentBlockDelta"in event :
                    delta =event ["contentBlockDelta"].get ("delta",{})
                    text =delta .get ("text","")
                    if text :
                        yield text 

                if "contentBlockStart"in event :
                    start =event ["contentBlockStart"].get ("start",{})
                    if "toolUse"in start :
                        idx =event ["contentBlockStart"].get ("contentBlockIndex",0 )
                        pending_tool_calls [idx ]={
                        "id":start ["toolUse"].get ("toolUseId",""),
                        "name":start ["toolUse"].get ("name",""),
                        "arguments":"",
                        }

                if "contentBlockDelta"in event :
                    delta =event ["contentBlockDelta"].get ("delta",{})
                    if "toolUse"in delta :
                        idx =event ["contentBlockDelta"].get ("contentBlockIndex",0 )
                        if idx in pending_tool_calls :
                            pending_tool_calls [idx ]["arguments"]+=delta ["toolUse"].get ("input","")

                if "messageStop"in event :
                    stop_reason =event ["messageStop"].get ("stopReason","")
                    if stop_reason =="tool_use":
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
            logger .error (f"AWS Bedrock stream error: {e }")
            yield f"[Error connecting to AWS Bedrock: {e }]"

    async def generate (self ,messages :list )->str :
        if not self ._model :
            return "[Error: AWS Bedrock model not set]"
        max_tokens =self .get_max_output_tokens ()
        inference_config ={
        "maxTokens":max_tokens ,
        "temperature":self .temperature ,
        }
        body ={
        "modelId":self ._model ,
        "messages":self ._convert_messages (messages ),
        "inferenceConfig":inference_config ,
        }
        try :
            client =self ._get_client ()
            response =client .converse (**body )
            output =response .get ("output",{})
            message =output .get ("message",{})
            content =message .get ("content",[])
            texts =[c ["text"]for c in content if "text"in c ]
            return "".join (texts )if texts else ""
        except Exception as e :
            logger .error (f"AWS Bedrock generate error: {e }")
            return f"Error: {e }"

    async def fetch_models (self )->List [str ]:
        try :
            client =self ._get_client ()
            response =client .list_foundation_models (
            byInferenceType ="ON_DEMAND"
            )
            models =response .get ("modelSummaries",[])
            return sorted ([m ["modelId"]for m in models ])
        except Exception as e :
            logger .error (f"AWS Bedrock models fetch error: {e }")
        return []

    async def close (self ):
        self ._client =None 
