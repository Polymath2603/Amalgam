"""
Secrets management for API keys and credentials.
Stores keys in a restricted-access JSON file (mode 0o600).
Supports multiple named profiles for key rotation.
"""
import json 
import os 
import logging 
from pathlib import Path 
from typing import Optional ,Dict 

from backend .core .paths import SECRETS_PATH 

logger =logging .getLogger (__name__ )


class SecretsManager :
    def __init__ (self ,path :str =None ):
        self ._path =Path (path or SECRETS_PATH )
        self ._data :Dict [str ,Dict [str ,str ]]={}
        self ._load ()

    def _load (self ):
        if self ._path .exists ():
            try :
                self ._data =json .loads (self ._path .read_text ())or {}
            except (json .JSONDecodeError ,OSError )as e :
                logger .warning (f"Failed to load secrets: {e }")
                self ._data ={}

    def _save (self ):
        self ._path .write_text (json .dumps (self ._data ,indent =2 ))
        self ._path .chmod (0o600 )

    def get (self ,key :str ,profile :str ="default")->Optional [str ]:
        return self ._data .get (profile ,{}).get (key )

    def set (self ,key :str ,value :str ,profile :str ="default"):
        if profile not in self ._data :
            self ._data [profile ]={}
        self ._data [profile ][key ]=value 
        self ._save ()

    def delete (self ,key :str ,profile :str ="default"):
        self ._data .get (profile ,{}).pop (key ,None )
        self ._save ()

    def list_keys (self ,profile :str ="default")->list :
        return list (self ._data .get (profile ,{}).keys ())

    def list_profiles (self )->list :
        return list (self ._data .keys ())

    def rotate (self ,key :str ,new_value :str ,profile :str ="default")->Optional [str ]:
        old =self .get (key ,profile )
        self .set (key ,new_value ,profile )
        return old 


_SECRETS :Optional [SecretsManager ]=None 


def get_secrets ()->SecretsManager :
    global _SECRETS 
    if _SECRETS is None :
        _SECRETS =SecretsManager ()
    return _SECRETS 
