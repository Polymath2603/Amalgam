"""
Plugin system — simple event-driven hooks at lifecycle points.

Plugins register callbacks that are invoked at various points
in the agent loop, context building, and tool execution.
"""
import logging 
from typing import Any ,Callable ,List 

logger =logging .getLogger (__name__ )


class Plugin :
    name :str =""

    async def on_tool_definition (self ,tools :list [dict ])->list [dict ]:
        return tools 

    async def on_system_prompt (self ,prompt :str )->str :
        return prompt 

    async def on_messages (self ,messages :list [dict ])->list [dict ]:
        return messages 

    async def on_compaction (self ,summary :str )->str :
        return summary 

    async def on_tool_result (self ,tool_name :str ,args :dict ,result :str )->str :
        return result 


class PluginRegistry :
    def __init__ (self ):
        self ._plugins :dict [str ,Plugin ]={}

    def register (self ,plugin :Plugin ):
        if plugin .name in self ._plugins :
            logger .warning ("Overwriting plugin: %s",plugin .name )
        self ._plugins [plugin .name ]=plugin 
        logger .info ("Registered plugin: %s",plugin .name )

    def unregister (self ,name :str ):
        self ._plugins .pop (name ,None )

    @property 
    def all (self )->list [Plugin ]:
        return list (self ._plugins .values ())

    async def hook_tool_definition (self ,tools :list [dict ])->list [dict ]:
        for p in self ._plugins .values ():
            try :
                tools =await p .on_tool_definition (tools )
            except Exception as e :
                logger .error ("Plugin '%s' on_tool_definition failed: %s",p .name ,e )
        return tools 

    async def hook_system_prompt (self ,prompt :str )->str :
        for p in self ._plugins .values ():
            try :
                prompt =await p .on_system_prompt (prompt )
            except Exception as e :
                logger .error ("Plugin '%s' on_system_prompt failed: %s",p .name ,e )
        return prompt 

    async def hook_messages (self ,messages :list [dict ])->list [dict ]:
        for p in self ._plugins .values ():
            try :
                messages =await p .on_messages (messages )
            except Exception as e :
                logger .error ("Plugin '%s' on_messages failed: %s",p .name ,e )
        return messages 

    async def hook_compaction (self ,summary :str )->str :
        for p in self ._plugins .values ():
            try :
                summary =await p .on_compaction (summary )
            except Exception as e :
                logger .error ("Plugin '%s' on_compaction failed: %s",p .name ,e )
        return summary 

    async def hook_tool_result (self ,tool_name :str ,args :dict ,result :str )->str :
        for p in self ._plugins .values ():
            try :
                result =await p .on_tool_result (tool_name ,args ,result )
            except Exception as e :
                logger .error ("Plugin '%s' on_tool_result failed: %s",p .name ,e )
        return result 


_registry =PluginRegistry ()


def register (plugin :Plugin ):
    _registry .register (plugin )


def get_registry ()->PluginRegistry :
    return _registry 
