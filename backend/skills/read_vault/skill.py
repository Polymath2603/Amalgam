import os 
import logging 
from typing import Any 

from backend .skills .base import Skill 
from backend .paths import VAULT_DIR 
from backend .core .vault import VaultManager 

logger =logging .getLogger (__name__ )


class ReadVaultSkill (Skill ):
    name ="read_vault"
    description ="Search and retrieve notes from the personal knowledge vault"
    parameters ={
    "type":"object",
    "properties":{
    "query":{"type":"string","description":"Search keywords or filename to find"},
    "filename":{"type":"string","description":"Exact filename to read (optional, overrides query)"},
    },
    }

    async def execute (self ,args :dict [str ,Any ])->str :
        query =args .get ("query","").strip ()
        filename =args .get ("filename","").strip ()

        vault_path =str (VAULT_DIR )
        if not os .path .isdir (vault_path ):
            return "Vault directory does not exist"

        vault =VaultManager (vault_path )

        if filename :
            filepath =os .path .join (vault_path ,filename )
            if not os .path .isfile (filepath ):
                return f"File not found in vault: {filename }"
            try :
                with open (filepath )as f :
                    content =f .read ()
                return f"# {filename }\n\n{content .strip ()}"
            except Exception as e :
                return f"Error reading {filename }: {e }"

        if query :
            results =vault .search (query )
            if not results :
                return f"No vault entries found for: {query }"
            lines =[f"## Vault results for '{query }'"]
            for r in results [:5 ]:
                lines .append (f"- **{r .get ('filename','?')}**: {r .get ('snippet','')[:200 ]}")
            return "\n".join (lines )

        files =vault .list_files ()
        if not files :
            return "Vault is empty"
        return "Available vault files:\n"+"\n".join (f"- {f }"for f in files )
