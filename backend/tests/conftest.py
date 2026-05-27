import os 
import sys 
import pytest 

os .environ ["K_HEADLESS"]="1"
os .environ ["K_TESTING"]="1"

@pytest .fixture 
def settings ():
    from backend .core .config .settings import Settings 
    s =Settings ()
    return s 

@pytest .fixture 
def llm_router (settings ):
    from backend .core .llm import LLMRouter 
    return LLMRouter (settings =settings )

@pytest .fixture 
def mcp_client ():
    from backend .core .mcp .client import MCPClient 
    return MCPClient ()
