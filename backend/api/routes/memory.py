"""
Memory / session / facts API routes.
"""
import logging 

from fastapi import APIRouter, HTTPException
from backend .api .deps import memory
from backend.core.deprecated import deprecated 

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


@router .post ("/api/memory/session/{session_id}/rename")
@deprecated()
async def rename_session (session_id :str ,new_title :str ):
    try:
        title = await memory().rename_session(session_id, new_title)
        return {"status": "ok", "title": title}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router .get ("/api/memory/session/{session_id}/resume")
@deprecated()
async def resume_session (session_id :str ,turns :int =5 ):
    messages = memory().get_session_turns(session_id, turns)
    return {"messages": messages}


@router .post ("/api/memory/session/{session_id}/activate")
@deprecated()
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


@router .get ("/api/memory/search")
async def search_memory (q :str ="",scope :str ="session"):
    """Semantic search across conversation history.

    scope=session: search within current session only
    scope=all: search across all sessions
    """
    if not q :
        return {"results":[]}
    if scope =="all":
        results =await memory ().search_all_sessions (q ,top_k =10 )
    else :
        results =await memory ().get_relevant (q ,top_k =5 )
    return {"results":results }


