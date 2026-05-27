from backend .core .llm import LLMRouter 


class TestLLMRouter :
    def test_router_initializes (self ,llm_router ):
        from backend .core .config .settings import DEFAULTS 
        assert llm_router is not None 
        assert llm_router .provider ==DEFAULTS ["provider"]["active"]

    def test_openai_compat_providers (self ):
        assert "deepseek"in LLMRouter .OPENAI_COMPAT 
        assert "mistral"in LLMRouter .OPENAI_COMPAT 
        assert "together"in LLMRouter .OPENAI_COMPAT 
        assert "azure-openai"in LLMRouter .OPENAI_COMPAT 
        assert "alibaba"in LLMRouter .OPENAI_COMPAT 
        assert "huggingface"in LLMRouter .OPENAI_COMPAT 

    def test_native_providers (self ):
        assert "aws"in LLMRouter .NATIVE_PROVIDERS 
        assert "gcp"in LLMRouter .NATIVE_PROVIDERS 
        assert "gemini"in LLMRouter .NATIVE_PROVIDERS 
        assert "ollama"in LLMRouter .NATIVE_PROVIDERS 

    def test_all_provider_instances_created (self ,llm_router ):
        for p in LLMRouter .OPENAI_COMPAT |LLMRouter .NATIVE_PROVIDERS :
            llm_router .provider =p 
            inst =llm_router ._provider_instance ()
            assert inst is not None ,f"Provider {p } returned None"
            assert hasattr (inst ,"stream"),f"Provider {p } missing stream()"
            assert hasattr (inst ,"generate"),f"Provider {p } missing generate()"

    def test_unknown_provider_falls_back (self ,llm_router ):
        llm_router .provider ="nonexistent"
        inst =llm_router ._provider_instance ()
        assert inst is not None 

    def test_supports_native_tools (self ,llm_router ):
        assert isinstance (llm_router .supports_native_tools (),bool )

    def test_reload_settings (self ,llm_router ):
        from backend .core .config .settings import DEFAULTS 
        llm_router .reload_settings ()
        assert llm_router .provider ==DEFAULTS ["provider"]["active"]
