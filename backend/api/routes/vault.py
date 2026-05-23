"""
Vault / rules API routes.
"""
import os 
import logging 

from fastapi import APIRouter 
from backend .api .deps import settings 
from backend .paths import VAULT_DIR 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["vault"])


@router .get ("/api/rules")
async def get_rules ():
    vault_path =settings ().get ("vault.path",str (VAULT_DIR ))
    rules_path =os .path .join (vault_path ,"rules.md")
    if os .path .exists (rules_path ):
        with open (rules_path ,"r")as f :
            return {"content":f .read ()}
    return {"content":""}


@router .post ("/api/rules")
async def save_rules (body :dict ):
    vault_path =settings ().get ("vault.path",str (VAULT_DIR ))
    os .makedirs (vault_path ,exist_ok =True )
    rules_path =os .path .join (vault_path ,"rules.md")
    with open (rules_path ,"w")as f :
        f .write (body .get ("content",""))
    return {"status":"ok"}


@router .get ("/api/vault/files")
async def list_vault_files ():
    vault_path =settings ().get ("vault.path",str (VAULT_DIR ))
    if not os .path .exists (vault_path ):
        return {"files":[]}
    files =[]
    for f in os .listdir (vault_path ):
        fp =os .path .join (vault_path ,f )
        if os .path .isfile (fp ):
            files .append ({"name":f ,"size":os .path .getsize (fp )})
    return {"files":files }
