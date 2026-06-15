"""
MCP Client — connects to MCP servers via stdio or SSE transport, discovers tools, and calls them.
Supports both local (stdio) and remote (SSE/HTTP) MCP servers.
Integrates hook system, permission system, and tool analytics.
"""
import json
import time
import asyncio
import logging
from typing import Dict ,Any ,List ,Optional
from contextlib import AsyncExitStack
import os

# Graceful degradation when mcp package is not installed (e.g. Android/aarch64
# where pydantic-core can't build, or environments that don't need MCP tools).
_MCP_AVAILABLE = True
try :
    from mcp .client .stdio import stdio_client ,StdioServerParameters
    from mcp .client .sse import sse_client
    from mcp .client .session import ClientSession
except ModuleNotFoundError :
    _MCP_AVAILABLE = False
    ClientSession = object  # placeholder for type annotations

from backend .core .agent .permissions import ToolPermissions ,PermissionLevel
from backend .core .agent .hooks import ToolHooks
from backend .core .agent .analytics import ToolAnalytics

logger =logging .getLogger (__name__ )


class MCPClient :
    def __init__ (self ):
        self .sessions :Dict [str ,ClientSession ]={}
        self .tools_cache :Dict [str ,Any ]={}
        self .server_tool_map :Dict [str ,str ]={}
        self .exit_stack =AsyncExitStack ()
        self ._reconnect_tasks :Dict [str ,asyncio .Task ]={}
        self ._server_configs :Dict [str ,dict ]={}
        self ._server_stacks :Dict [str ,AsyncExitStack ]={}
        self ._agent =None
        self ._closed =False
        # New subsystems
        self .permissions =ToolPermissions ()
        self .hooks =ToolHooks ()
        self .analytics =ToolAnalytics ()

    def register_agent (self ,agent ):
        self ._agent =agent

    def set_permission_level (self ,level :str ):
        """Set the permission level for this session."""
        try :
            self .permissions .set_level (PermissionLevel (level ))
            logger .info (f"Permission level set to {level }")
        except ValueError :
            logger .warning (f"Invalid permission level: {level }")

    def approve_tool (self ,tool_name :str ):
        """Approve a tool for one-time use."""
        self .permissions .approve_tool_once (tool_name )

    def get_hook_context (self )->dict :
        return {
            "level":self .permissions .level .value ,
            "approved_once":list (self .permissions ._approved_once ),
        }

    async def _close_server (self ,name :str ):
        """Close an individual server's session and transport."""
        old_stack =self ._server_stacks .pop (name ,None )
        if old_stack :
            try :
                await old_stack .aclose ()
            except BaseException as e :
                logger .debug (f"Error closing server {name } stack: {e }")
        self .sessions .pop (name ,None )

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
                await self ._connect_from_config (server_name ,server_config )

    async def connect_from_settings (self ,servers :List [Dict ]):
        """Connect to MCP servers from settings config (parallel)."""
        coros =[]
        names =[]
        for server_config in servers :
            if not server_config .get ("enabled",True ):
                continue
            name =server_config .get ("name")
            if name :
                coros .append (self ._connect_from_config (name ,server_config ))
                names .append (name )
        if coros :
            results =await asyncio .gather (*coros ,return_exceptions =True )
            for name ,r in zip (names ,results ):
                if isinstance (r ,Exception ):
                    logger .error (f"MCP server {name } connection failed: {r }")

    async def _connect_from_config (self ,name :str ,config :dict ):
        """Connect a server from a config dict. Supports stdio and SSE."""
        self ._server_configs [name ]=config
        if "url"in config :
            ok =await self ._connect_sse (name ,config ["url"],config .get ("headers",{}))
        else :
            cmd =config .get ("command")
            args =config .get ("args",[])
            env =config .get ("env",None )
            ok =await self ._connect_server (name ,cmd ,args ,env )
        if not ok :
            task =asyncio .create_task (self ._reconnect_loop (name ))
            self ._reconnect_tasks [name ]=task

    async def _connect_server (self ,name :str ,cmd :str ,args :List [str ],
    env :Optional [Dict [str ,str ]]=None ,timeout :float =15.0 ):
        """Connect to a stdio-based MCP server."""
        if not _MCP_AVAILABLE :
            logger .warning (f"Cannot connect to stdio MCP server {name } — mcp package not installed")
            return False
        logger .debug (f"Connecting to stdio MCP server: {name }")
        if self ._closed :
            return False

        await self ._close_server (name )
        server_env =os .environ .copy ()
        local_bin =os .path .join (os .path .expanduser ("~"),".local","bin")
        server_env ["PATH"]=f"{local_bin }:{server_env .get ('PATH','')}"
        server_env ["COREPACK_ENABLE_STRICT"]="0"
        server_env ["npm_config_user_agent"]="npm"
        if env :
            server_env .update (env )

        server_params =StdioServerParameters (command =cmd ,args =args ,env =server_env )
        stack =AsyncExitStack ()

        try :
            stdio_transport =await asyncio .wait_for (
            stack .enter_async_context (stdio_client (server_params )),
            timeout =timeout
            )
            read_stream ,write_stream =stdio_transport
            session =await asyncio .wait_for (
            stack .enter_async_context (ClientSession (read_stream ,write_stream )),
            timeout =timeout
            )
            await asyncio .wait_for (session .initialize (),timeout =timeout )
            self ._server_stacks [name ]=stack
            self .sessions [name ]=session
            await self ._discover_tools (name ,session )
            logger .debug (f"Connected to stdio server {name }")
            return True
        except asyncio .TimeoutError :
            logger .error (f"Timeout connecting to stdio server {name } ({timeout }s)")
            await stack .aclose ()
            return False
        except BaseException as e :
            logger .error (f"Failed to connect to stdio server {name }: [{type (e ).__name__ }] {e }")
            await stack .aclose ()
            if isinstance (e ,(asyncio .CancelledError ,KeyboardInterrupt )):
                raise
            return False

    async def _connect_sse (self ,name :str ,url :str ,headers :dict =None ,
    timeout :float =15.0 ):
        """Connect to a remote SSE/HTTP MCP server."""
        if not _MCP_AVAILABLE :
            logger .warning (f"Cannot connect to SSE MCP server {name } — mcp package not installed")
            return False
        logger .debug (f"Connecting to SSE MCP server: {name } at {url }")
        if self ._closed :
            return False

        await self ._close_server (name )
        stack =AsyncExitStack ()

        try :
            transport =await asyncio .wait_for (
            stack .enter_async_context (sse_client (url ,headers =headers or {})),
            timeout =timeout
            )
            read_stream ,write_stream =transport
            session =await asyncio .wait_for (
            stack .enter_async_context (ClientSession (read_stream ,write_stream )),
            timeout =timeout
            )
            await asyncio .wait_for (session .initialize (),timeout =timeout )
            self ._server_stacks [name ]=stack
            self .sessions [name ]=session
            await self ._discover_tools (name ,session )
            logger .debug (f"Connected to SSE server {name }")
            return True
        except asyncio .TimeoutError :
            logger .error (f"Timeout connecting to SSE server {name } ({timeout }s)")
            await stack .aclose ()
            return False
        except BaseException as e :
            logger .error (f"Failed to connect to SSE server {name }: {e }")
            await stack .aclose ()
            if isinstance (e ,(asyncio .CancelledError ,KeyboardInterrupt )):
                raise
            return False

    async def _discover_tools (self ,name :str ,session :ClientSession ):
        """Discover tools from a connected session."""
        try :

            stale =[t for t ,s in self .server_tool_map .items ()if s ==name ]
            for t in stale :
                self .tools_cache .pop (t ,None )
                self .server_tool_map .pop (t ,None )

            tools_response =await session .list_tools ()
            for tool in tools_response .tools :
                self .tools_cache [tool .name ]=tool
                self .server_tool_map [tool .name ]=name
            logger .debug (f"Discovered {len (tools_response .tools )} tools from {name }")
        except Exception as e :
            logger .error (f"Failed to discover tools from {name }: {e }")

    async def _reconnect_loop (self ,name :str ,delay :int =1 ):
        config =self ._server_configs .get (name ,{})
        while not self ._closed and delay <=15 :
            await asyncio .sleep (delay )
            logger .debug (f"Reconnecting to {name }...")
            if "url"in config :
                ok =await self ._connect_sse (name ,config ["url"],config .get ("headers",{}))
            else :
                ok =await self ._connect_server (
                name ,config .get ("command",""),
                config .get ("args",[]),config .get ("env")
                )
            if ok :
                return
            delay =min (delay *2 ,16 )
        if not self ._closed :
            logger .error (f"Max reconnect delay reached for {name }")

    def has_servers (self )->bool :
        """True if at least one external MCP server is connected."""
        return bool (self .sessions )

    async def wait_for_tools (self ,timeout :float =10.0 ,min_tools :int =1 )->bool :
        """Wait until at least `min_tools` tools are discovered, or timeout."""
        t0 =time .monotonic ()
        while time .monotonic ()-t0 <timeout :
            if len (self .tools_cache )>=min_tools :
                return True
            await asyncio .sleep (0.1 )
        return False

    def get_tool_schema (self )->List [Dict [str ,Any ]]:
        schema =[]
        for name ,tool in self .tools_cache .items ():
            schema .append ({
            "type":"function",
            "function":{
            "name":tool .name ,
            "description":tool .description ,
            "parameters":tool .inputSchema
            }
            })
        if self ._agent is not None :
            schema .append ({
            "type":"function",
            "function":{
            "name":"task",
            "description":"Spawn a sub-agent to handle a focused, self-contained task. The sub-agent has the same capabilities (MCP tools, LLM) but runs in an isolated context. Use this for tasks that are independent of the current conversation. Returns the sub-agent's complete output.",
            "parameters":{
            "type":"object",
            "properties":{
            "prompt":{
            "type":"string",
            "description":"Detailed instructions for the sub-agent"
            }
            },
            "required":["prompt"]
            }
            }
            })
        return schema

    async def call_tool (self ,name :str ,arguments :dict )->str :
        """Call a tool with permission checks, hooks, and analytics."""
        t0 =time .monotonic ()
        success =False
        error =None

        try :
            # Permission check
            allowed ,reason =self .permissions .check_tool_allowed (name )
            if not allowed :
                error =reason or f"Tool {name } not allowed"
                return f"Error: {error }"

            # Pre-hooks
            hook_ctx ={"tool":name ,"args":arguments ,"level":self .permissions .level .value }
            hook_result =await self .hooks .run_pre (name ,arguments ,hook_ctx )
            if hook_result and "error"in hook_result :
                error =hook_result ["error"]
                return f"Error: {error }"

            # Execute
            if name =="task"and self ._agent is not None :
                prompt =arguments .get ("prompt","")
                result =await self ._agent .spawn_subagent (prompt )
            elif name not in self .server_tool_map :
                error =f"Tool {name } not found"
                return f"Error: {error }"
            else :
                server_name =self .server_tool_map [name ]
                session =self .sessions .get (server_name )
                if not session :
                    error =f"Session for {name } not available"
                    return f"Error: {error }"
                result_obj =await session .call_tool (name ,arguments )
                if not result_obj .content :
                    result =""
                else :
                    parts =[]
                    for c in result_obj .content :
                        if c .type =="text":
                            parts .append (c .text )
                        elif c .type =="image":
                            parts .append (f"[Image: {c .mimeType } data={len (c .data )} bytes]")
                            parts .append (f"data:{c .mimeType };base64,{c .data }")
                    result ="\n".join (parts )

            success =True
            return result

        except Exception as e :
            error =str (e )
            return f"Error calling tool {name }: {error }"

        finally :
            latency_ms =(time .monotonic ()-t0 )*1000
            self .analytics .record_call (name ,arguments ,latency_ms ,success ,error )
            post_ctx ={"tool":name ,"args":arguments ,"result":error if error else "ok" }
            await self .hooks .run_post (name ,arguments ,post_ctx )

    async def close (self ):
        self ._closed =True
        self .analytics .persist ()
        tasks =[t for t in self ._reconnect_tasks .values ()if not t .done ()]
        for t in tasks :
            t .cancel ()
        if tasks :
            await asyncio .gather (*tasks ,return_exceptions =True )
        self ._reconnect_tasks .clear ()
        for name in list (self ._server_stacks .keys ()):
            await self ._close_server (name )
        await self .exit_stack .aclose ()
        self .sessions .clear ()
        self .tools_cache .clear ()
        self .server_tool_map .clear ()
        self ._agent =None
