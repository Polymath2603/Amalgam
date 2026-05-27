"""
Centralized structured logging configuration.
Wraps Python's standard logging with structlog for JSON/colored output.
"""
import os 
import sys 
import logging 
import structlog 

LOG_LEVELS ={
"DEBUG":logging .DEBUG ,
"INFO":logging .INFO ,
"WARNING":logging .WARNING ,
"ERROR":logging .ERROR ,
"CRITICAL":logging .CRITICAL ,
}

DEFAULT_LEVEL ="ERROR"
DEFAULT_FORMAT ="console"

_configured =False 


def configure_logging (
level :str =None ,
log_format :str =None ,
module_levels :dict =None ,
):
    """
    Configure structured logging. Idempotent — safe to call multiple times.

    Args:
        level: Root log level (DEBUG/INFO/WARNING/ERROR/CRITICAL). Falls back to env LOG_LEVEL, then DEFAULT_LEVEL.
        log_format: "json" or "console". Falls back to env LOG_FORMAT, then DEFAULT_FORMAT.
        module_levels: Per-module log levels, e.g. {"backend.core.mcp": "DEBUG", "backend.api": "INFO"}
    """
    global _configured 

    level =level or os .environ .get ("LOG_LEVEL")or DEFAULT_LEVEL 
    log_format =log_format or os .environ .get ("LOG_FORMAT")or DEFAULT_FORMAT 
    root_level =LOG_LEVELS .get (level .upper (),logging .WARNING )

    module_levels =module_levels or {}

    if not _configured :
        shared_processors =[
        structlog .stdlib .add_log_level ,
        structlog .stdlib .add_logger_name ,
        structlog .processors .TimeStamper (fmt ="iso"),
        structlog .processors .StackInfoRenderer (),
        structlog .contextvars .merge_contextvars ,
        structlog .dev .set_exc_info ,
        ]

        if log_format =="json":
            renderer =structlog .processors .JSONRenderer ()
        else :
            renderer =structlog .dev .ConsoleRenderer (
            colors =sys .stderr .isatty (),
            sort_keys =False ,
            )

        structlog .configure (
        processors =[
        structlog .stdlib .filter_by_level ,
        *shared_processors ,
        structlog .stdlib .ProcessorFormatter .wrap_for_formatter ,
        ],
        logger_factory =structlog .stdlib .LoggerFactory (),
        cache_logger_on_first_use =True ,
        )

        formatter =structlog .stdlib .ProcessorFormatter (
        foreign_pre_chain =shared_processors ,
        processors =[
        structlog .stdlib .ProcessorFormatter .remove_processors_meta ,
        renderer ,
        ],
        )

        handler =logging .StreamHandler (sys .stdout )
        handler .setFormatter (formatter )

        root_logger =logging .getLogger ()
        root_logger .addHandler (handler )
        root_logger .setLevel (root_level )

        for h in root_logger .handlers [:-1 ]:
            if isinstance (h ,logging .StreamHandler )and h .stream in (sys .stdout ,sys .stderr ):
                root_logger .removeHandler (h )

        logging .getLogger ("uvicorn.access").setLevel (logging .WARNING )
        logging .getLogger ("uvicorn.error").setLevel (logging .WARNING )

        logging .getLogger ("httpx").setLevel (logging .WARNING )
        logging .getLogger ("httpcore").setLevel (logging .WARNING )
        logging .getLogger ("chromadb").setLevel (logging .WARNING )

        _configured =True 
    elif root_level !=logging .getLogger ().level :
        logging .getLogger ().setLevel (root_level )

    for module ,lvl in module_levels .items ():
        logging .getLogger (module ).setLevel (LOG_LEVELS .get (lvl .upper (),logging .WARNING ))

    return structlog .get_logger ()
