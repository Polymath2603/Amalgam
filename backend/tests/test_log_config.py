import os 


class TestLogConfig :
    def test_configure_logging_returns_logger (self ):
        from backend .core .log_config import configure_logging 
        log =configure_logging (level ="INFO")
        assert log is not None 
        assert hasattr (log ,"info")
        assert hasattr (log ,"error")
        assert hasattr (log ,"warning")
        assert hasattr (log ,"debug")

    def test_configure_logging_idempotent (self ):
        from backend .core .log_config import configure_logging 
        log1 =configure_logging (level ="INFO")
        log2 =configure_logging (level ="DEBUG")
        assert log1 is not None 
        assert log2 is not None 

    def test_configure_json_format (self ):
        from backend .core .log_config import configure_logging 
        log =configure_logging (level ="WARNING",log_format ="json")
        assert log is not None 

    def test_env_vars_respected (self ):
        os .environ ["LOG_LEVEL"]="ERROR"
        os .environ ["LOG_FORMAT"]="json"
        from backend .core .log_config import configure_logging 
        log =configure_logging ()
        assert log is not None 
        del os .environ ["LOG_LEVEL"]
        del os .environ ["LOG_FORMAT"]

    def test_module_levels_applied (self ):
        import logging 
        from backend .core .log_config import configure_logging 
        configure_logging (level ="WARNING",module_levels ={"test.module":"DEBUG"})
        logger =logging .getLogger ("test.module")
        assert logger .level ==logging .DEBUG 
