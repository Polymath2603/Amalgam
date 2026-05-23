import asyncio 
import logging 
from typing import Any 

from backend .skills .base import Skill 

logger =logging .getLogger (__name__ )


class WebSearchSkill (Skill ):
    name ="web_search"
    description ="Search the web for current information using DuckDuckGo (no API key needed)"
    parameters ={
    "type":"object",
    "properties":{
    "query":{"type":"string","description":"The search query"},
    "num_results":{"type":"integer","description":"Number of results to return (default 5)"},
    },
    "required":["query"],
    }

    async def execute (self ,args :dict [str ,Any ])->str :
        query =args .get ("query","")
        num_results =int (args .get ("num_results",5 ))
        if not query :
            return "Error: query is required"

        try :
            import httpx 
            async with httpx .AsyncClient (timeout =15.0 )as client :
                resp =await client .get (
                "https://html.duckduckgo.com/html/",
                params ={"q":query },
                headers ={
                "User-Agent":(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
                )
                },
                )
                resp .raise_for_status ()
                html =resp .text 

            import re 
            results =[]
            for i ,match in enumerate (re .finditer (
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html ,re .DOTALL 
            )):
                if i >=num_results :
                    break 
                url =match .group (1 )
                title =re .sub (r'<[^>]+>','',match .group (2 )).strip ()
                results .append (f"{i +1 }. [{title }]({url })")

            if not results :
                return f"No results found for '{query }'"

            return "\n".join (results )

        except ImportError :
            return "Error: httpx is required for web_search. Install with: pip install httpx"
        except Exception as e :
            logger .error (f"web_search failed: {e }")
            return f"Search failed: {e }"
