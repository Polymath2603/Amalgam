"""
Character / animation / voice / model API routes.
"""
import os 
import logging 
import asyncio 
import shutil 

from pathlib import Path 
from fastapi import APIRouter 
from fastapi .responses import JSONResponse 
from backend .api .deps import settings ,llm ,tts 
from backend .core .config .settings import BUILTIN_VOICES 
from backend .core .llm import LLMRouter 
from backend .core .paths import CHARACTERS_DIR ,PROJECT_ROOT ,DATA_DIR 
from backend .core .utils .icon_generator import _generate_missing_icons_sync ,generate_missing_icons ,PALETTE 

logger =logging .getLogger (__name__ )
router =APIRouter (tags =["characters"])


@router .get ("/api/characters")
async def get_characters ():
    """Return all available characters with their full definitions."""
    return settings ().get_characters ()


@router .get ("/api/characters/{character_id}")
async def get_character (character_id :str ):
    """Get a specific character's definition."""
    chars =settings ().get_characters ()
    if character_id in chars :
        return chars [character_id ]
    return JSONResponse (status_code =404 ,content ={"error":"Character not found"})


def _list_anim_files (base_dir :Path )->list :
    """List .vrma files in an animation directory, or empty list."""
    if not base_dir .is_dir ():
        return []
    result =[]
    for f in sorted (os .listdir (str (base_dir ))):
        if f .endswith (".vrma"):
            result .append (f )
    return result 

@router .get ("/api/animations")
async def get_animations (char_id :str =None ):
    """Return available VRMA animation files."""
    animations ={"default":[],"character":[]}

    seen =set ()
    for base in [CHARACTERS_DIR ]:
        for f in _list_anim_files (base /"default"/"anim"):
            if f not in seen :
                seen .add (f )
                name =f .replace (".vrma","").replace (".bvh","")
                animations ["default"].append ({
                "file":f ,
                "name":name ,
                "url":f"/static/animations/{f }"
                })

    if char_id and char_id !="default":
        seen =set ()
        for base in [CHARACTERS_DIR ]:
            for f in _list_anim_files (base /char_id /"anim"):
                if f not in seen :
                    seen .add (f )
                    name =f .replace (".vrma","").replace (".bvh","")
                    animations ["character"].append ({
                    "file":f ,
                    "name":name ,
                    "url":f"/characters/{char_id }/anim/{f }"
                    })

    return animations 


@router .get ("/api/emotions")
async def get_emotions ():
    return {"emotions":tts ().get_supported_emotions ()}


@router .get ("/api/expressions")
async def get_expressions (char_id :str =None ):
    from backend .core .context_builder import VRM_EXPRESSIONS 
    exprs =list (VRM_EXPRESSIONS )
    return {"expressions":exprs }


@router .get ("/api/voices")
async def get_voices ():
    return BUILTIN_VOICES 


@router .get ("/api/models/ollama")
async def get_ollama_models ():
    models =await llm ().fetch_ollama_models ()
    return {"models":models }


@router .get ("/api/models/gemini")
async def get_gemini_models ():
    models =await llm ().fetch_gemini_models ()
    return {"models":models }


@router .get ("/api/models/{provider}")
async def get_provider_models (provider :str ):
    if provider =="ollama":
        models =await llm ().fetch_ollama_models ()
        return {"models":models }
    if provider =="gemini":
        models =await llm ().fetch_gemini_models ()
        return {"models":models }
    if provider in LLMRouter .OPENAI_COMPAT :
        fresh_llm =LLMRouter (settings =settings ())
        models =await fresh_llm .fetch_openai_compat_models (provider )
        await fresh_llm .close ()
        return {"models":models }
    if provider =="claude":
        return {"models":["claude-sonnet-4-20250514","claude-3-5-sonnet-20241022",
        "claude-3-opus-20240229","claude-3-haiku-20240307"]}
    if provider =="aws":
        fresh_llm =LLMRouter (settings =settings ())
        models =await fresh_llm .fetch_bedrock_models ()
        await fresh_llm .close ()
        return {"models":models }
    if provider =="gcp":
        fresh_llm =LLMRouter (settings =settings ())
        models =await fresh_llm .fetch_vertex_models ()
        await fresh_llm .close ()
        return {"models":models }
    return JSONResponse (status_code =400 ,content ={"error":f"Unknown provider: {provider }"})


@router .post ("/api/icons/regenerate")
async def regenerate_icons ():
    """Regenerate character icons. Tries VRM renderer first, then letter-based fallback."""
    vrm_output =""
    vrm_ok =False 

    char_dirs =sorted ([
    d for d in os .listdir (str (CHARACTERS_DIR ))
    if os .path .isdir (os .path .join (str (CHARACTERS_DIR ),d ))
    ])
    for char_dir in char_dirs :
        icon_path =os .path .join (str (CHARACTERS_DIR ),char_dir ,"icon.png")
        if os .path .exists (icon_path ):
            os .remove (icon_path )

    node =shutil .which ("node")
    vrm_script =os .path .join (str (PROJECT_ROOT ),"backend","scripts","generate-icons-vrm.js")
    if node and os .path .exists (vrm_script ):
        try :
            logger .debug ("Running VRM icon generation...")
            proc =await asyncio .create_subprocess_exec (
            node ,vrm_script ,"--all",
            stdout =asyncio .subprocess .PIPE ,
            stderr =asyncio .subprocess .PIPE ,
            cwd =str (PROJECT_ROOT )
            )
            stdout ,stderr =await asyncio .wait_for (proc .communicate (),timeout =300 )
            vrm_output =stdout .decode ()+stderr .decode ()
            vrm_ok =proc .returncode ==0 
            logger .debug (f"VRM icon gen result (ok={vrm_ok }): {vrm_output }")
        except Exception as e :
            logger .error (f"VRM icon generation crashed: {e }")

    _generate_missing_icons_sync ()

    return {
    "status":"ok",
    "method":"vrm+letter"if vrm_ok else "letter",
    "vrm_output":vrm_output if vrm_output else None ,
    }
