"""
Skill MCP server — combines SKILL.md knowledge management with legacy skill execution.

Knowledge tools (SKILL.md on-demand loading, matching OpenCode/Claude pattern):
  - skill(name)         Load a SKILL.md file's content
  - create_skill(...)   Create a new SKILL.md skill
  - delete_skill(name)  Delete a skill
  - list_skills()       List available skills with name + description

Code-execution tools (migrated from old Python Skill classes):
  - web_search(query, num_results)    Search the web via DuckDuckGo
  - summarize_url(url)                Fetch and extract a webpage
  - note(title, content, tags)        Save a note to the vault
  - read_vault(query, filename)       Search/read vault notes
  - reminder(text, delay_seconds)     Set an in-process timer
"""
import os 
import re 
import sys 
import json 
import shutil 
import asyncio 
import logging 
from pathlib import Path 
from typing import Optional 

from mcp .server import Server 
from mcp .types import Tool ,TextContent 

logger =logging .getLogger (__name__ )

app =Server ("skill-server")




PROJECT_ROOT =Path (os .path .abspath (os .path .join (os .path .dirname (__file__ ),"..","..","..","..")))
BUILTIN_SKILLS =PROJECT_ROOT /"backend"/"skills"
DATA_DIR =Path (os .environ .get ("AMALGAM_DATA_DIR",str (PROJECT_ROOT /"user_data")))
USER_SKILLS =DATA_DIR /"skills"
VAULT_DIR =DATA_DIR /"vault"


def _discover_skill_files ()->list [dict ]:
    """Scan user_data/skills/ for SKILL.md files, copying missing built-ins first.

    Returns a list of {name, description, source_dir, path} dicts.
    """
    os .makedirs (str (USER_SKILLS ),exist_ok =True )
    os .makedirs (str (BUILTIN_SKILLS ),exist_ok =True )


    for entry in sorted (os .listdir (str (BUILTIN_SKILLS ))):
        src =BUILTIN_SKILLS /entry 
        dst =USER_SKILLS /entry 
        if entry .startswith ("__")or entry .startswith ("."):
            continue 
        if src .is_dir ()and not dst .exists ():
            try :
                shutil .copytree (str (src ),str (dst ),ignore =shutil .ignore_patterns ("__pycache__","*.py"))
                logger .info ("Installed built-in skill '%s' to user data",entry )
            except Exception as e :
                logger .warning ("Failed to copy skill '%s': %s",entry ,e )


    skills =[]
    if USER_SKILLS .is_dir ():
        for entry in sorted (os .listdir (str (USER_SKILLS ))):
            skill_md =USER_SKILLS /entry /"SKILL.md"
            if skill_md .is_file ():
                try :
                    content =skill_md .read_text (encoding ="utf-8")
                    name ,description =_parse_frontmatter (content )
                    if name :
                        skills .append ({
                        "name":name ,
                        "description":description or "",
                        "path":str (skill_md ),
                        })
                except Exception as e :
                    logger .warning ("Failed to parse skill '%s': %s",entry ,e )
    return skills 


def _parse_frontmatter (content :str )->tuple [Optional [str ],Optional [str ]]:
    """Extract name and description from YAML frontmatter in a SKILL.md file."""
    lines =content .split ("\n")
    if not lines or lines [0 ].strip ()!="---":
        return None ,None 
    end =1 
    while end <len (lines )and lines [end ].strip ()!="---":
        end +=1 
    if end >=len (lines ):
        return None ,None 
    name =None 
    description =None 
    for line in lines [1 :end ]:
        if line .startswith ("name:"):
            name =line [len ("name:"):].strip ().strip ("\"'")
        elif line .startswith ("description:"):
            description =line [len ("description:"):].strip ().strip ("\"'")
    return name ,description 





@app .list_tools ()
async def list_tools ()->list [Tool ]:
    tools =[
    Tool (
    name ="skill",
    description ="Load a skill's full content by name. Returns SKILL.md content to inject into context.",
    inputSchema ={
    "type":"object",
    "properties":{
    "name":{"type":"string","description":"The exact skill name"}
    },
    "required":["name"],
    },
    ),
    Tool (
    name ="create_skill",
    description ="Create a new SKILL.md skill that the AI can later load and use. Skills are markdown files with YAML frontmatter.",
    inputSchema ={
    "type":"object",
    "properties":{
    "name":{"type":"string","description":"Unique skill name (lowercase, hyphenated)"},
    "description":{"type":"string","description":"Short description shown in the skills list"},
    "content":{"type":"string","description":"Full markdown content (without frontmatter — name/description are auto-generated)"},
    },
    "required":["name","description","content"],
    },
    ),
    Tool (
    name ="delete_skill",
    description ="Delete an existing skill by name.",
    inputSchema ={
    "type":"object",
    "properties":{
    "name":{"type":"string","description":"The exact skill name to delete"}
    },
    "required":["name"],
    },
    ),
    Tool (
    name ="list_skills",
    description ="List all available skills with their name and description.",
    inputSchema ={
    "type":"object",
    "properties":{},
    },
    ),

    Tool (
    name ="web_search",
    description ="Search the web for current information using DuckDuckGo (no API key needed). Returns ranked results with titles and URLs.",
    inputSchema ={
    "type":"object",
    "properties":{
    "query":{"type":"string","description":"The search query"},
    "num_results":{"type":"integer","description":"Number of results (default 5)","default":5 },
    },
    "required":["query"],
    },
    ),
    Tool (
    name ="summarize_url",
    description ="Fetch a webpage and extract its readable text content. Removes navigation, scripts, styling. Good for reading articles or docs.",
    inputSchema ={
    "type":"object",
    "properties":{
    "url":{"type":"string","description":"The URL to fetch and extract"},
    },
    "required":["url"],
    },
    ),
    Tool (
    name ="note",
    description ="Save a note to the personal knowledge vault as a markdown file. Notes persist and are searchable via read_vault.",
    inputSchema ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Note title (used as filename)"},
    "content":{"type":"string","description":"The note content in markdown format"},
    "tags":{"type":"string","description":"Comma-separated tags (optional)"},
    },
    "required":["title","content"],
    },
    ),
    Tool (
    name ="read_vault",
    description ="Search for or read notes from the personal knowledge vault. If no query or filename given, lists all files.",
    inputSchema ={
    "type":"object",
    "properties":{
    "query":{"type":"string","description":"Keywords to search for (optional)"},
    "filename":{"type":"string","description":"Exact filename to read (optional, overrides query)"},
    },
    },
    ),
    Tool (
    name ="reminder",
    description ="Set a timer or reminder that fires after a delay and logs a message. Note: timers are in-process and lost on server restart.",
    inputSchema ={
    "type":"object",
    "properties":{
    "text":{"type":"string","description":"The reminder message"},
    "delay_seconds":{"type":"integer","description":"Seconds to wait (default 60)","default":60 },
    },
    "required":["text"],
    },
    ),
    ]
    return tools 





_active_timers :dict [str ,asyncio .Task ]={}


def _clean_timer (timer_id :str ):
    _active_timers .pop (timer_id ,None )





@app .call_tool ()
async def call_tool (name :str ,arguments :dict )->list [TextContent ]:
    if name =="list_skills":
        skills =_discover_skill_files ()
        if not skills :
            return [TextContent (type ="text",text ="No skills found.")]
        lines =["Available skills:"]
        for s in skills :
            desc =s ["description"]or "No description"
            lines .append (f"- **{s ['name']}**: {desc }")
        return [TextContent (type ="text",text ="\n".join (lines ))]

    if name =="skill":
        skill_name =arguments .get ("name","").strip ()
        if not skill_name :
            return [TextContent (type ="text",text ="Error: name is required.")]
        skills =_discover_skill_files ()
        for s in skills :
            if s ["name"]==skill_name :
                content =Path (s ["path"]).read_text (encoding ="utf-8")
                return [TextContent (type ="text",text =content )]
        return [TextContent (type ="text",text =f"Error: skill '{skill_name }' not found.")]

    if name =="create_skill":
        skill_name =arguments .get ("name","").strip ()
        description =arguments .get ("description","").strip ()
        content =arguments .get ("content","").strip ()
        if not skill_name or not content :
            return [TextContent (type ="text",text ="Error: name and content are required.")]

        safe_name =re .sub (r"[^a-z0-9_-]","_",skill_name .lower ())
        skill_dir =USER_SKILLS /safe_name 
        os .makedirs (str (skill_dir ),exist_ok =True )

        md =f"---\nname: {skill_name }\ndescription: {description }\n---\n\n{content }\n"
        (skill_dir /"SKILL.md").write_text (md ,encoding ="utf-8")
        return [TextContent (type ="text",text =f"Skill '{skill_name }' created successfully.")]

    if name =="delete_skill":
        skill_name =arguments .get ("name","").strip ()
        if not skill_name :
            return [TextContent (type ="text",text ="Error: name is required.")]
        skills =_discover_skill_files ()
        for s in skills :
            if s ["name"]==skill_name :
                skill_dir =Path (s ["path"]).parent 
                shutil .rmtree (str (skill_dir ),ignore_errors =True )
                return [TextContent (type ="text",text =f"Skill '{skill_name }' deleted.")]
        return [TextContent (type ="text",text =f"Error: skill '{skill_name }' not found.")]

    if name =="web_search":
        query =arguments .get ("query","")
        num_results =int (arguments .get ("num_results",5 ))
        if not query :
            return [TextContent (type ="text",text ="Error: query is required.")]
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
                return [TextContent (type ="text",text =f"No results found for '{query }'")]
            return [TextContent (type ="text",text ="\n".join (results ))]
        except ImportError :
            return [TextContent (type ="text",text ="Error: httpx is required. Install with: pip install httpx")]
        except Exception as e :
            logger .error ("web_search failed: %s",e )
            return [TextContent (type ="text",text =f"Search failed: {e }")]

    if name =="summarize_url":
        url =arguments .get ("url","").strip ()
        if not url :
            return [TextContent (type ="text",text ="Error: url is required.")]
        try :
            import httpx 
            from bs4 import BeautifulSoup 
        except ImportError :
            return [TextContent (type ="text",text ="httpx and beautifulsoup4 required: pip install httpx beautifulsoup4")]
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
            text ="\n".join (lines )[:4000 ]
            return [TextContent (type ="text",text =f"# {title }\n\n{text [:3000 ]}")]
        except Exception as e :
            logger .error ("summarize_url failed for %s: %s",url ,e )
            return [TextContent (type ="text",text =f"Failed to fetch {url }: {e }")]

    if name =="note":
        title =arguments .get ("title","").strip ()
        content =arguments .get ("content","").strip ()
        tags =arguments .get ("tags","").strip ()
        if not title or not content :
            return [TextContent (type ="text",text ="Error: title and content are required.")]
        sanitized ="".join (c if c .isalnum ()or c in " _-"else "_"for c in title ).rstrip ()
        if not sanitized :
            sanitized ="note"
        filename =f"{sanitized }.md"
        os .makedirs (str (VAULT_DIR ),exist_ok =True )
        header =f"# {title }\n"
        if tags :
            header +=f"Tags: {tags }\n"
        header +="---\n\n"
        (VAULT_DIR /filename ).write_text (header +content ,encoding ="utf-8")
        return [TextContent (type ="text",text =f"Note saved: {filename }")]

    if name =="read_vault":
        query =arguments .get ("query","").strip ()
        filename =arguments .get ("filename","").strip ()
        if not VAULT_DIR .is_dir ():
            return [TextContent (type ="text",text ="Vault directory does not exist.")]
        if filename :
            path =VAULT_DIR /filename 
            if not path .is_file ():
                return [TextContent (type ="text",text =f"File not found: {filename }")]
            try :
                text =path .read_text (encoding ="utf-8")
                return [TextContent (type ="text",text =f"# {filename }\n\n{text .strip ()}")]
            except Exception as e :
                return [TextContent (type ="text",text =f"Error reading {filename }: {e }")]
        if query :
            from backend .core .vault import VaultManager 
            vault =VaultManager (str (VAULT_DIR ))
            results =vault .search (query )
            if not results :
                return [TextContent (type ="text",text =f"No vault entries found for: {query }")]
            lines =[f"## Vault results for '{query }'"]
            for r in results [:5 ]:
                lines .append (f"- **{r .get ('filename','?')}**: {r .get ('snippet','')[:200 ]}")
            return [TextContent (type ="text",text ="\n".join (lines ))]
        files =sorted (f .name for f in VAULT_DIR .iterdir ()if f .is_file ())
        if not files :
            return [TextContent (type ="text",text ="Vault is empty.")]
        return [TextContent (type ="text",text ="Available vault files:\n"+"\n".join (f"- {f }"for f in files ))]

    if name =="reminder":
        text =arguments .get ("text","")
        delay =int (arguments .get ("delay_seconds",60 ))
        if not text :
            return [TextContent (type ="text",text ="Error: text is required.")]
        timer_id =f"reminder_{id (text )}_{delay }"
        if timer_id in _active_timers :
            return [TextContent (type ="text",text ="Timer already exists for this reminder.")]

        async def _fire ():
            try :
                await asyncio .sleep (delay )
                logger .info ("REMINDER: %s",text )
            except asyncio .CancelledError :
                pass 
            finally :
                _clean_timer (timer_id )

        task =asyncio .create_task (_fire ())
        _active_timers [timer_id ]=task 
        if delay <60 :
            display =f"{delay }s"
        elif delay <3600 :
            display =f"{delay //60 }m {delay %60 }s"
        else :
            display =f"{delay //3600 }h {(delay %3600 )//60 }m"
        return [TextContent (type ="text",text =f"Reminder set: \"{text }\" will fire in {display }")]

    raise ValueError (f"Unknown tool: {name }")


if __name__ =="__main__":
    from mcp .server .stdio import stdio_server 
    async def run ():
        async with stdio_server ()as (read_stream ,write_stream ):
            await app .run (read_stream ,write_stream ,app .create_initialization_options ())
    asyncio .run (run ())
