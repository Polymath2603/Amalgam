"""
Vault / rules API routes.
"""
import os 
import logging 

from fastapi import APIRouter
from pydantic import BaseModel
from backend .api .deps import settings ,vault ,llm
from backend .core .paths import VAULT_DIR
from backend.core.deprecated import deprecated 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["vault"])


class RulesSaveRequest(BaseModel):
    content: str = ""


class VaultFileWriteRequest(BaseModel):
    content: str = ""


@router .get ("/api/rules")
@deprecated()
async def get_rules ():
    content =vault ().read ("rules.md")
    return {"content":content or ""}


@router .post ("/api/rules")
@deprecated()
async def save_rules (body :RulesSaveRequest ):
    vault ().write ("rules.md",body .content)
    return {"status":"ok"}


@router .get ("/api/vault/files")
@deprecated()
async def list_vault_files ():
    return {"files":vault ().list_files ()}


@router .get ("/api/vault/files/{filename}")
@deprecated()
async def read_vault_file (filename :str ):
    content =vault ().read (filename )
    if content is None :
        return {"error":"File not found","content":None }
    return {"name":filename ,"content":content }


@router .post ("/api/vault/files/{filename}")
@deprecated()
async def write_vault_file (filename :str ,body :VaultFileWriteRequest ):
    ok =vault ().write (filename ,body .content)
    return {"status":"ok"if ok else "error"}


@router .delete ("/api/vault/files/{filename}")
@deprecated()
async def delete_vault_file (filename :str ):
    ok =vault ().delete (filename )
    return {"status":"ok"if ok else "error"}


@router .get ("/api/vault/search")
@deprecated()
async def search_vault (q :str ="",mode :str ="keyword",max_results :int =5 ):
    """Search vault files.

    mode=keyword: fast text matching (existing behavior)
    mode=semantic: ChromaDB embedding-based search
    """
    if not q :
        return {"results":[]}
    if mode =="semantic":
        llm_router =llm ()
        results =await vault ().semantic_search (
        q ,
        get_embedding_fn =llm_router .get_embedding if llm_router else None ,
        top_k =max_results ,
        )
        return {"results":results ,"mode":"semantic"}
    results =vault ().search (q ,max_results =max_results )
    return {"results":results ,"mode":"keyword"}
