import os 
import sys 
import shutil 
import importlib .util 
import logging 
from typing import Any 

from backend .skills .base import Skill 
from backend .paths import SKILLS_DIR 

logger =logging .getLogger (__name__ )

_BUILTIN_SKILLS =os .path .join (os .path .dirname (__file__ ))


class SkillLoader :
    def __init__ (self ,skills_dir :str =None ):
        self .skills_dir =skills_dir or str (SKILLS_DIR )
        self ._skills :dict [str ,Skill ]={}
        self ._ensure_skills ()

    def _ensure_skills (self ):
        if not os .path .isdir (self .skills_dir ):
            os .makedirs (self .skills_dir ,exist_ok =True )
        existing =set ()
        if os .path .isdir (self .skills_dir ):
            existing ={d for d in os .listdir (self .skills_dir )
            if os .path .isdir (os .path .join (self .skills_dir ,d ))}
        builtins =set ()
        if os .path .isdir (_BUILTIN_SKILLS ):
            builtins ={d for d in os .listdir (_BUILTIN_SKILLS )
            if os .path .isdir (os .path .join (_BUILTIN_SKILLS ,d ))
            and d not in ("__pycache__",)}
        missing =builtins -existing 
        for name in missing :
            src =os .path .join (_BUILTIN_SKILLS ,name )
            dst =os .path .join (self .skills_dir ,name )
            try :
                shutil .copytree (src ,dst ,ignore =shutil .ignore_patterns ("__pycache__"))
                logger .info (f"Installed built-in skill '{name }' to user data")
            except Exception as e :
                logger .warning (f"Failed to copy skill '{name }': {e }")

    def _load_skill_module (self ,skill_path :str ):
        module_name =f"_user_skill_{os .path .basename (os .path .dirname (skill_path ))}"
        spec =importlib .util .spec_from_file_location (module_name ,skill_path )
        if spec is None or spec .loader is None :
            return None 
        module =importlib .util .module_from_spec (spec )
        sys .modules [module_name ]=module 
        spec .loader .exec_module (module )
        return module 

    def discover (self ):
        self ._skills ={}
        if not os .path .isdir (self .skills_dir ):
            return 

        for entry in sorted (os .listdir (self .skills_dir )):
            skill_path =os .path .join (self .skills_dir ,entry ,"skill.py")
            if not os .path .isfile (skill_path ):
                continue 
            try :
                module =self ._load_skill_module (skill_path )
                if module is None :
                    continue 
                for attr_name in dir (module ):
                    attr =getattr (module ,attr_name )
                    if isinstance (attr ,type )and issubclass (attr ,Skill )and attr is not Skill :
                        skill_instance =attr ()
                        if skill_instance .name :
                            self ._skills [skill_instance .name ]=skill_instance 
                            logger .info (f"Discovered skill: {skill_instance .name } ({skill_path })")
            except Exception as e :
                logger .warning (f"Failed to load skill from {skill_path }: {e }")

    def get_tools (self )->list [dict [str ,Any ]]:
        tools =[]
        for name ,skill in self ._skills .items ():
            tools .append ({
            "name":skill .name ,
            "description":skill .description ,
            "parameters":skill .parameters ,
            })
        return tools 

    async def execute (self ,name :str ,arguments :dict [str ,Any ])->str :
        skill =self ._skills .get (name )
        if not skill :
            return f"Error: Skill '{name }' not found"
        try :
            return await skill .execute (arguments )
        except Exception as e :
            logger .error (f"Skill '{name }' failed: {e }")
            return f"Error executing skill '{name }': {e }"
