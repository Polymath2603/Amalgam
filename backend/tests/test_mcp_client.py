import pytest 


class TestMCPClient :
    def test_client_initializes (self ,mcp_client ):
        assert mcp_client is not None 
        assert mcp_client .sessions =={}
        assert mcp_client .tools_cache =={}
        assert mcp_client ._closed is False 

    def test_register_agent (self ,mcp_client ):
        mcp_client .register_agent ("fake_agent")
        assert mcp_client ._agent =="fake_agent"

    def test_get_tool_schema_no_agent (self ,mcp_client ):
        schema =mcp_client .get_tool_schema ()
        assert schema ==[]

    def test_get_tool_schema_with_agent (self ,mcp_client ):
        mcp_client .register_agent (object ())
        schema =mcp_client .get_tool_schema ()
        names =[t ["function"]["name"]for t in schema ]
        assert "task"in names 
        assert all (t ["type"]=="function"for t in schema )

    def test_call_tool_no_session (self ,mcp_client ):
        result =mcp_client .call_tool ("nonexistent",{})
        import asyncio 
        result =asyncio .run (result )
        assert "Error"in result 

    def test_close_cleanup (self ,mcp_client ):
        import asyncio 
        asyncio .run (mcp_client .close ())
        assert mcp_client ._closed is True 
        assert mcp_client .sessions =={}
        assert mcp_client .tools_cache =={}
        assert mcp_client .server_tool_map =={}

    def test_double_close_safe (self ,mcp_client ):
        import asyncio 
        asyncio .run (mcp_client .close ())
        asyncio .run (mcp_client .close ())
        assert mcp_client ._closed is True 
