"""
MCP Client — connects to MCP servers via stdio transport, discovers tools, and calls them.
Supports both JSON config file and settings-based server lists.
"""
import json 
import asyncio 
import logging 
from typing import Dict ,Any ,List ,Optional 
from mcp .client .stdio import stdio_client ,StdioServerParameters 
from mcp .client .session import ClientSession 
from contextlib import AsyncExitStack 
import os 

logger =logging .getLogger (__name__ )


class MCPClient :
    def __init__ (self ):
        self .sessions :Dict [str ,ClientSession ]={}
        self .tools_cache :Dict [str ,Any ]={}
        self .server_tool_map :Dict [str ,str ]={}
        self .exit_stack =AsyncExitStack ()
        self ._reconnect_tasks ={}

    async def connect_servers (self ,config_path :str ):
        """Connect to MCP servers defined in a JSON config file."""
        try :
            with open (config_path ,"r")as f :
                config =json .load (f )
        except Exception as e :
            logger .error (f"Failed to load MCP config: {e }")
            return 

        for server_name ,server_config in config .items ():
            if isinstance (server_config ,dict ):
                enabled =server_config .get ("enabled",True )
                if not enabled :
                    continue 
                cmd =server_config .get ("command")
                args =server_config .get ("args",[])
                env =server_config .get ("env",None )
                ok =await self ._connect_server (server_name ,cmd ,args ,env )
                if not ok :
                    task =asyncio .create_task (self ._reconnect (server_name ,cmd ,args ,env ))
                    self ._reconnect_tasks [server_name ]=task 

    async def connect_from_settings (self ,servers :List [Dict ]):
        """Connect to MCP servers from settings config."""
        for server_config in servers :
            if not server_config .get ("enabled",True ):
                continue 
            name =server_config .get ("name")
            cmd =server_config .get ("command")
            args =server_config .get ("args",[])
            env =server_config .get ("env",None )
            if name and cmd :
                ok =await self ._connect_server (name ,cmd ,args ,env )
                if not ok :
                    task =asyncio .create_task (self ._reconnect (name ,cmd ,args ,env ))
                    self ._reconnect_tasks [name ]=task 

    async def _connect_server (self ,name :str ,cmd :str ,args :List [str ],
    env :Optional [Dict [str ,str ]]=None ,timeout :float =15.0 ):
        """Returns True on success, False on failure."""
        logger .debug (f"Connecting to MCP server: {name }")
        server_env =os .environ .copy ()
        if env :
            server_env .update (env )

        server_params =StdioServerParameters (command =cmd ,args =args ,env =server_env )

        try :
            stdio_transport =await asyncio .wait_for (
            self .exit_stack .enter_async_context (stdio_client (server_params )),
            timeout =timeout 
            )
            read_stream ,write_stream =stdio_transport 
            session =await asyncio .wait_for (
            self .exit_stack .enter_async_context (ClientSession (read_stream ,write_stream )),
            timeout =timeout 
            )

            await asyncio .wait_for (session .initialize (),timeout =timeout )
            self .sessions [name ]=session 


            tools_response =await asyncio .wait_for (session .list_tools (),timeout =timeout )
            for tool in tools_response .tools :
                self .tools_cache [tool .name ]=tool 
                self .server_tool_map [tool .name ]=name 

            logger .debug (f"Connected to {name } and discovered {len (tools_response .tools )} tools")
            return True 

        except asyncio .TimeoutError :
            logger .error (f"Timeout connecting to MCP server {name } ({timeout }s)")
            return False 
        except Exception as e :
            logger .error (f"Failed to connect to {name }: {e }")
            return False 

    async def _reconnect (self ,name :str ,cmd :str ,args :List [str ],
    env :Optional [Dict [str ,str ]],delay =1 ):
        if delay >15 :
            logger .error (f"Max reconnect delay reached for {name }")
            return 

        await asyncio .sleep (delay )
        logger .debug (f"Attempting to reconnect to {name }...")
        ok =await self ._connect_server (name ,cmd ,args ,env ,timeout =10.0 )
        if not ok :
            task =asyncio .create_task (self ._reconnect (name ,cmd ,args ,env ,delay =min (delay *2 ,16 )))
            self ._reconnect_tasks [name ]=task 

    def get_tool_schema (self )->List [Dict [str ,Any ]]:
        schema =[]
        for name ,tool in self .tools_cache .items ():
            schema .append ({
            "name":tool .name ,
            "description":tool .description ,
            "parameters":tool .inputSchema 
            })
        return schema 

    async def call_tool (self ,name :str ,arguments :dict )->str :
        if name not in self .server_tool_map :
            return f"Error: Tool {name } not found"

        server_name =self .server_tool_map [name ]
        session =self .sessions .get (server_name )

        if not session :
            return f"Error: Session for {server_name } not available"

        try :
            result =await session .call_tool (name ,arguments )
            if not result .content :
                return ""
            parts =[]
            for c in result .content :
                if c .type =="text":
                    parts .append (c .text )
                elif c .type =="image":
                    parts .append (f"[Image: {c .mimeType } data={len (c .data )} bytes]")
                    parts .append (f"data:{c .mimeType };base64,{c .data }")
            return "\n".join (parts )
        except Exception as e :
            return f"Error calling tool {name }: {e }"

    async def close (self ):
        await self .exit_stack .aclose ()
