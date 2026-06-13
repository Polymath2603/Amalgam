import json 
import os 

from backend .core .config .settings import Settings 


class TestSettings :
    def test_defaults_loaded (self ,settings ):
        from backend .core .config .settings import DEFAULTS 
        assert settings is not None 
        assert settings .get ("provider.active","")!=""
        assert DEFAULTS ["provider"]["gemini"]["model"]=="gemini-2.5-flash"

    def test_get_with_dotpath (self ,settings ):
        assert settings .get ("provider.active")!=""
        assert settings .get ("provider.ollama.base_url")=="http://localhost:11434"
        assert settings .get ("nonexistent.key","default")=="default"

    def test_set_and_get (self ,settings ):
        settings .set ("test.key","value")
        assert settings .get ("test.key")=="value"

    def test_set_nested (self ,settings ):
        settings .set ("a.b.c","deep")
        assert settings .get ("a.b.c")=="deep"
        assert settings .get ("a.b")=={"c":"deep"}

    def test_get_mcp_servers (self ,settings ):
        servers =settings .get_mcp_servers ()
        assert isinstance (servers ,list )
        assert len (servers )>0 
        names =[s ["name"]for s in servers ]
        assert "shell"in names 
        assert "avatar"in names 
        assert "screenshot"in names 

    def test_all_providers_have_defaults (self ,settings ):
        from backend .core .config .settings import DEFAULTS 
        defaults =DEFAULTS .get ("provider",{})
        providers =["gemini","ollama","openrouter","zai","siliconflow","groq",
        "chatgpt","claude","llamacpp","koboldai",
        "deepseek","mistral","together","azure-openai",
        "alibaba","huggingface","aws","gcp"]
        for p in providers :
            assert p in defaults ,f"Missing default section for {p }"
            cfg =defaults [p ]
            assert isinstance (cfg ,dict ),f"Default for {p } is not a dict"
            assert len (cfg )>0 ,f"Default for {p } is empty"

    def test_get_characters (self ,settings ):
        chars =settings .get_characters ()
        assert "default"in chars 
        assert chars ["default"]["name"]=="Assistant"
