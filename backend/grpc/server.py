"""
gRPC server — wraps the agent for external integrations (CI/CD, custom UIs, CLI).
Bidirectional streaming for real-time text chunks, tool calls, and permission requests.
"""
import asyncio 
import json 
import logging 
from concurrent import futures 

import grpc 
from backend .grpc import agent_pb2 ,agent_pb2_grpc 
from k_core .deps import get_shared 

logger =logging .getLogger (__name__ )


class AgentService (agent_pb2_grpc .AgentServiceServicer ):
    def __init__ (self ):
        self ._current_session =None 

    async def Chat (self ,request_iterator ,context ):
        shared =get_shared ()
        agent =shared ["agent"]

        async for req in request_iterator :
            which =req .WhichOneof ("payload")
            if which =="text":
                text =req .text 
                async for chunk in agent .handle_user_input (text ):
                    if isinstance (chunk ,tuple ):
                        tag_type ,tag_val =chunk 
                        if tag_type =="__thinking__":
                            yield agent_pb2 .ChatResponse (thinking =tag_val )
                        elif tag_type =="__permission__":
                            yield agent_pb2 .ChatResponse (
                            permission_request =agent_pb2 .PermissionRequest (
                            cmd =tag_val ,
                            options =["once","prefix","exact","deny"]
                            )
                            )
                        elif tag_type =="__tool__":
                            yield agent_pb2 .ChatResponse (
                            tool_call =agent_pb2 .ToolCall (name =tag_val ,args_json ="{}")
                            )
                        elif tag_type =="__error__":
                            yield agent_pb2 .ChatResponse (error =tag_val )
                    else :
                        yield agent_pb2 .ChatResponse (text_chunk =chunk )
                yield agent_pb2 .ChatResponse (done =True )

            elif which =="permission_action":
                action =req .permission_action 
                logger .info ("gRPC permission %s for: %s",action .action ,action .cmd )
                yield agent_pb2 .ChatResponse (text_chunk =f"[Permission {action .action }]")


async def serve_grpc (host :str ="0.0.0.0",port :int =50051 ):
    server =grpc .aio .server (
    futures .ThreadPoolExecutor (max_workers =10 ),
    options =[
    ("grpc.max_send_message_length",100 *1024 *1024 ),
    ("grpc.max_receive_message_length",100 *1024 *1024 ),
    ],
    )
    agent_pb2_grpc .add_AgentServiceServicer_to_server (AgentService (),server )
    server .add_insecure_port (f"{host }:{port }")
    await server .start ()
    logger .info ("gRPC server listening on %s:%s",host ,port )
    await server .wait_for_termination ()


if __name__ =="__main__":
    logging .basicConfig (level =logging .INFO )
    asyncio .run (serve_grpc ())
