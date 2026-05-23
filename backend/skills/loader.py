import os 
import sys 
import importlib 
import logging 
from typing import Any 

from .base import Skill 

logger =logging .getLogger (__name__ )


class SkillLoader :
    def __init__ (self ,skills_dir :str =None ):
        self .skills_dir =skills_dir or os .path .join (os .path .dirname (__file__ ))
        self ._skills :dict [str ,Skill ]={}

    def discover (self ):
        self ._skills ={}
        if not os .path .isdir (self .skills_dir ):
            return 

        for entry in sorted (os .listdir (self .skills_dir )):
            skill_path =os .path .join (self .skills_dir ,entry ,"skill.py")
            if not os .path .isfile (skill_path ):
                continue 
            try :
                module_name =f"backend.skills.{entry }.skill"
                if module_name in sys .modules :
                    module =importlib .reload (sys .modules [module_name ])
                else :
                    module =importlib .import_module (module_name )
                for attr_name in dir (module ):
                    attr =getattr (module ,attr_name )
                    if isinstance (attr ,type )and issubclass (attr ,Skill )and attr is not Skill :
                        skill_instance =attr ()
                        if skill_instance .name :
                            self ._skills [skill_instance .name ]=skill_instance 
                            logger .info (f"Discovered skill: {skill_instance .name }")
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
