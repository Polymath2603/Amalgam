from backend.core.llm import LLMRouter
import pytest


class TestLLMRouter:
    def test_router_initializes(self, llm_router):
        assert llm_router is not None
        assert llm_router._provider is not None

    def test_supports_native_tools(self, llm_router):
        assert isinstance(llm_router.supports_native_tools(), bool)

    def test_get_max_output_tokens(self, llm_router):
        val = llm_router.get_max_output_tokens()
        assert isinstance(val, int)
        assert val > 0

    def test_get_context_token_limit(self, llm_router):
        val = llm_router.get_context_token_limit()
        assert isinstance(val, int)
        assert val > 0

    def test_reload_settings(self, llm_router):
        llm_router.reload_settings()
        assert llm_router._provider is not None

    @pytest.mark.asyncio
    async def test_close(self, llm_router):
        await llm_router.close()
