from typing import Any 


class Skill :
    name :str =""
    description :str =""
    parameters :dict ={"type":"object","properties":{}}

    async def execute (self ,args :dict [str ,Any ])->str :
        raise NotImplementedError 
