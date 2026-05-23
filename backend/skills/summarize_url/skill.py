import logging 
from typing import Any 

from backend .skills .base import Skill 

logger =logging .getLogger (__name__ )


class SummarizeUrlSkill (Skill ):
    name ="summarize_url"
    description ="Fetch a webpage and summarize its content"
    parameters ={
    "type":"object",
    "properties":{
    "url":{"type":"string","description":"The URL to fetch and summarize"},
    },
    "required":["url"],
    }

    async def execute (self ,args :dict [str ,Any ])->str :
        url =args .get ("url","").strip ()
        if not url :
            return "Error: url is required"

        try :
            import httpx 
            from bs4 import BeautifulSoup 
        except ImportError :
            return "Error: httpx and beautifulsoup4 required. Install with: pip install httpx beautifulsoup4"

        try :
            async with httpx .AsyncClient (timeout =20.0 ,follow_redirects =True )as client :
                resp =await client .get (
                url ,
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

            soup =BeautifulSoup (html ,"html.parser")

            for tag in soup (["script","style","nav","footer","header","aside"]):
                tag .decompose ()

            title =soup .title .string .strip ()if soup .title and soup .title .string else url 
            text =soup .get_text (separator ="\n",strip =True )
            lines =[l .strip ()for l in text .splitlines ()if l .strip ()]
            text ="\n".join (lines )

            if len (text )>4000 :
                text =text [:4000 ]+"\n\n[...content truncated at 4000 chars]"

            return f"# {title }\n\n{text [:3000 ]}"

        except Exception as e :
            logger .error (f"summarize_url failed for {url }: {e }")
            return f"Failed to fetch {url }: {e }"
