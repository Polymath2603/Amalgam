"""
Standalone vault manager.
Reads/writes markdown files in the vault directory and provides
search functionality independent of any MCP server.
"""
import os 
import re 
import logging 
from pathlib import Path 
from typing import List ,Dict ,Optional 

logger =logging .getLogger (__name__ )


class VaultManager :
    def __init__ (self ,vault_path :str ):
        self ._vault_path =Path (vault_path )

    @property 
    def vault_path (self )->Path :
        return self ._vault_path 

    def list_files (self )->List [Dict ]:
        """List all files in the vault directory with metadata."""
        if not self ._vault_path .exists ():
            return []
        files =[]
        for f in sorted (self ._vault_path .iterdir ()):
            if f .is_file ():
                files .append ({
                "name":f .name ,
                "size":f .stat ().st_size ,
                "modified":f .stat ().st_mtime ,
                })
        return files 

    def read (self ,filename :str )->Optional [str ]:
        """Read a specific vault file, returning its content or None."""
        path =self ._vault_path /filename 
        if not path .exists ()or not path .is_file ():
            return None 
        try :
            return path .read_text (encoding ="utf-8")
        except Exception as e :
            logger .error (f"Failed to read vault file {filename }: {e }")
            return None 

    def write (self ,filename :str ,content :str )->bool :
        """Write content to a vault file (creates or overwrites)."""
        self ._vault_path .mkdir (parents =True ,exist_ok =True )
        path =self ._vault_path /filename 
        try :
            path .write_text (content ,encoding ="utf-8")
            return True 
        except Exception as e :
            logger .error (f"Failed to write vault file {filename }: {e }")
            return False 

    def delete (self ,filename :str )->bool :
        """Delete a vault file."""
        path =self ._vault_path /filename 
        if not path .exists ():
            return False 
        try :
            path .unlink ()
            return True 
        except Exception as e :
            logger .error (f"Failed to delete vault file {filename }: {e }")
            return False 

    def search (self ,query :str ,max_results :int =5 )->List [Dict ]:
        """Simple keyword search across all markdown files in the vault.
        
        Returns up to max_results file snippets ranked by keyword density.
        """
        if not self ._vault_path .exists ():
            return []
        query_lower =query .lower ()
        query_words =set (query_lower .split ())
        scored =[]

        for f in self ._vault_path .iterdir ():
            if not f .is_file ()or not f .name .endswith (".md"):
                continue 
            try :
                content =f .read_text (encoding ="utf-8")
            except Exception :
                continue 
            content_lower =content .lower ()

            matches =sum (1 for w in query_words if w in content_lower )
            if matches ==0 :
                continue 

            word_count =len (content_lower .split ())
            density =matches /max (word_count ,1 )
            score =density *100 +matches *10 


            snippet =""
            for word in query_words :
                idx =content_lower .find (word )
                if idx !=-1 :
                    start =max (0 ,idx -60 )
                    end =min (len (content ),idx +len (word )+60 )
                    snippet =content [start :end ].strip ()
                    if start >0 :
                        snippet ="..."+snippet 
                    if end <len (content ):
                        snippet =snippet +"..."
                    break 

            scored .append ({
            "filename":f .name ,
            "score":round (score ,1 ),
            "snippet":snippet or content [:200 ],
            "size":f .stat ().st_size ,
            })

        scored .sort (key =lambda x :x ["score"],reverse =True )
        return scored [:max_results ]

    def tag_search (self ,tag :str ,max_results :int =10 )->List [Dict ]:
        """Search for files containing a specific #tag."""
        if not self ._vault_path .exists ():
            return []
        pattern =re .compile (rf'#\s*{re .escape (tag )}\b',re .IGNORECASE )
        results =[]
        for f in self ._vault_path .iterdir ():
            if not f .is_file ()or not f .name .endswith (".md"):
                continue 
            try :
                content =f .read_text (encoding ="utf-8")
            except Exception :
                continue 
            matches =pattern .findall (content )
            if matches :
                results .append ({
                "filename":f .name ,
                "tag":tag ,
                "match_count":len (matches ),
                })
        return results [:max_results ]

    def inject_to_context (self ,max_tokens :int =2000 )->str :
        """Read all .md files up to max_tokens and return formatted context string.
        
        Returns empty string if no vault files or vault_path doesn't exist.
        """
        from backend .utils .tokens import estimate_tokens ,truncate_to_token_limit 

        if not self ._vault_path .exists ():
            return ""

        sections =[]
        chars_used =0 

        chars_budget =max_tokens *4 

        for f in sorted (self ._vault_path .iterdir ()):
            if not f .is_file ()or not f .name .endswith (".md"):
                continue 
            try :
                content =f .read_text (encoding ="utf-8").strip ()
            except Exception :
                continue 
            if not content :
                continue 

            remaining =chars_budget -chars_used 
            if remaining <=0 :
                break 

            if len (content )>remaining :
                content =truncate_to_token_limit (content ,estimate_tokens (content [:remaining ])or 1 )

            section_name =f .stem .replace ("_"," ").title ()
            sections .append (f"\n\n## Vault: {section_name }\n{content }")
            chars_used +=len (content )

        if sections :
            result ="".join (sections )
            logger .debug (f"Injected {len (sections )} vault file(s) ({chars_used } chars)")
            return result 
        return ""
