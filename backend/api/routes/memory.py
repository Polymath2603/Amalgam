"""
Memory / session / facts API routes.
"""
import logging 

from fastapi import APIRouter 
from backend .api .deps import memory 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["memory"])


@router .get ("/api/memory/sessions")
async def get_sessions ():
    sessions =memory ().get_sessions ()
    return {"sessions":sessions ,"current":memory ().get_current_session ()}


@router .get ("/api/memory/session/{session_id}")
async def get_session_messages (session_id :str ):
    if session_id =="current":
        session_id =memory ().get_current_session ()
    else :
        memory ().set_current_session (session_id )
    messages =memory ().get_session_messages (session_id )
    exists =memory ().session_exists (session_id )or len (messages )>0 
    return {"messages":messages ,"session_id":session_id ,"exists":exists }


@router .post ("/api/memory/session/{session_id}/activate")
async def activate_session (session_id :str ):
    """Switch the active session to an existing one."""
    memory ().set_current_session (session_id )
    messages =memory ().get_session_messages (session_id )
    return {"session_id":session_id ,"messages":messages ,"status":"ok"}


@router .delete ("/api/memory/session/{session_id}")
async def delete_session (session_id :str ):
    await memory ().delete_session (session_id )
    return {"status":"ok"}


@router .post ("/api/memory/clear")
async def clear_memory ():
    await memory ().clear ()
    memory ().start_session ()
    return {"status":"ok"}


@router .get ("/api/memory/session/current")
async def get_current_session_messages ():
    sid =memory ().get_current_session ()
    messages =memory ().get_session_messages (sid )
    return {"session_id":sid ,"messages":messages }


@router .post ("/api/memory/new-session")
async def create_new_session ():
    sid =memory ().start_session ()
    return {"session_id":sid ,"status":"ok"}


@router .get ("/api/facts")
async def get_facts (category :str =None ,limit :int =100 ):
    facts =memory ().get_facts (category =category ,limit =limit )
    return {"facts":facts }


@router .post ("/api/memory/facts")
async def add_fact_endpoint (body :dict ):
    await memory ().add_fact (
    str (body .get ("fact","")),
    category =str (body .get ("category","general")),
    importance =float (body .get ("importance",0.5 )),
    )
    return {"status":"ok"}


@router .delete ("/api/facts/{fact_id}")
async def delete_fact (fact_id :int ):
    await memory ().delete_fact (fact_id )
    return {"status":"ok"}
