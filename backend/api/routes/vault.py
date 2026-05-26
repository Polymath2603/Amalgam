"""
Vault / rules API routes.
"""
import os 
import logging 

from fastapi import APIRouter 
from backend .api .deps import settings ,vault 
from backend .core .paths import VAULT_DIR 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["vault"])


@router .get ("/api/rules")
async def get_rules ():
    content =vault ().read ("rules.md")
    return {"content":content or ""}


@router .post ("/api/rules")
async def save_rules (body :dict ):
    vault ().write ("rules.md",body .get ("content",""))
    return {"status":"ok"}


@router .get ("/api/vault/files")
async def list_vault_files ():
    return {"files":vault ().list_files ()}


@router .get ("/api/vault/files/{filename}")
async def read_vault_file (filename :str ):
    content =vault ().read (filename )
    if content is None :
        return {"error":"File not found","content":None }
    return {"name":filename ,"content":content }


@router .post ("/api/vault/files/{filename}")
async def write_vault_file (filename :str ,body :dict ):
    ok =vault ().write (filename ,body .get ("content",""))
    return {"status":"ok"if ok else "error"}


@router .delete ("/api/vault/files/{filename}")
async def delete_vault_file (filename :str ):
    ok =vault ().delete (filename )
    return {"status":"ok"if ok else "error"}


@router .get ("/api/vault/search")
async def search_vault (q :str ="",max_results :int =5 ):
    if not q :
        return {"results":[]}
    results =vault ().search (q ,max_results =max_results )
    return {"results":results }
