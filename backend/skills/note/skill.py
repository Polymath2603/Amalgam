import os 
import logging 
from typing import Any 

from backend .skills .base import Skill 
from backend .paths import VAULT_DIR 

logger =logging .getLogger (__name__ )


class NoteSkill (Skill ):
    name ="note"
    description ="Save a note to the personal knowledge vault for later reference"
    parameters ={
    "type":"object",
    "properties":{
    "title":{"type":"string","description":"Note title (used as filename)"},
    "content":{"type":"string","description":"The note content in markdown format"},
    "tags":{"type":"string","description":"Comma-separated tags for the note"},
    },
    "required":["title","content"],
    }

    async def execute (self ,args :dict [str ,Any ])->str :
        title =args .get ("title","").strip ()
        content =args .get ("content","").strip ()
        tags =args .get ("tags","").strip ()
        if not title or not content :
            return "Error: title and content are required"

        sanitized ="".join (c if c .isalnum ()or c in " _-"else "_"for c in title ).rstrip ()
        if not sanitized :
            sanitized ="note"
        filename =f"{sanitized }.md"

        os .makedirs (str (VAULT_DIR ),exist_ok =True )
        filepath =os .path .join (str (VAULT_DIR ),filename )

        header =f"# {title }\n"
        if tags :
            header +=f"Tags: {tags }\n"
        header +=f"---\n\n"

        full_content =header +content 

        try :
            with open (filepath ,"w")as f :
                f .write (full_content )
            logger .info (f"Saved note: {filepath }")
            return f"Note saved: {filename }"
        except Exception as e :
            logger .error (f"Failed to save note: {e }")
            return f"Error saving note: {e }"
