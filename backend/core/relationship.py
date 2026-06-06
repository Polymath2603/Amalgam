import json
import math
import os
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Dict

import aiosqlite
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_VADER = SentimentIntensityAnalyzer()

logger =logging .getLogger (__name__ )

POSITIVE_WORDS ={
"love","like","great","amazing","wonderful","fantastic","good","nice",
"happy","glad","beautiful","excellent","awesome","perfect","best",
"thank","thanks","appreciate","fun","enjoy","delight","welcome",
"adorable","charming","warm","caring","kind","sweet","lovely",
"brilliant","fascinating","interesting","cool","wow","yes"
}

NEGATIVE_WORDS ={
"hate","bad","terrible","awful","horrible","worst","ugly","sad",
"angry","mad","annoy","frustrat","stupid","dumb","boring","disappoint",
"useless","waste","shut","leave","stop","no","wrong","loser",
"pathetic","ridiculous"
}

DEPTH_MARKERS ={"why","how","because","think","feel","believe","imagine",
"perhaps","maybe","wonder","suppose","curious","explain",
"mean","purpose","reason","meaning","what if"}

SECONDS_PER_DAY =86400 
DECAY_RATE_PER_DAY =0.05 

STAGES =[
("stranger",{"interaction_count":0 ,"avg_sentiment":0.0 ,"avg_depth":0.0 }),
("acquaintance",{"interaction_count":5 ,"avg_sentiment":0.0 ,"avg_depth":0.0 }),
("friend",{"interaction_count":20 ,"avg_sentiment":0.3 ,"avg_depth":0.15 }),
("close_friend",{"interaction_count":50 ,"avg_sentiment":0.5 ,"avg_depth":0.3 }),
("intimate",{"interaction_count":100 ,"avg_sentiment":0.7 ,"avg_depth":0.5 }),
]


class Relationship :
    def __init__ (self ,db_path :str =None ):
        from backend .core .paths import RELATIONSHIP_DB 
        if db_path is None :
            db_path =RELATIONSHIP_DB 
        self ._db_path =str (db_path)
        os .makedirs (os .path .dirname (self._db_path ),exist_ok =True )
        self ._cache :Dict [str ,Dict ]={}

    async def _init_db(self):
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute('''
                CREATE TABLE IF NOT EXISTS relationships (
                    character_id TEXT PRIMARY KEY,
                    stats TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            await db.commit()

    def _default_stats (self )->Dict :
        now =datetime .now (timezone .utc ).isoformat ()
        return {
        "interaction_count":0 ,
        "avg_sentiment":0.5 ,
        "avg_depth":0.1 ,
        "total_words_user":0 ,
        "total_words_assistant":0 ,
        "last_interaction":now ,
        "created_at":now ,
        }

    async def _load (self ,character_id :str )->Dict :
        if character_id in self ._cache :
            return self ._cache [character_id ]
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                'SELECT stats FROM relationships WHERE character_id = ?',
                (character_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row :
            stats =json .loads (row [0 ])
            self ._cache [character_id ]=stats 
            return stats 
        stats =self ._default_stats ()
        self ._cache [character_id ]=stats 
        return stats 

    async def _save (self ,character_id :str ,stats :Dict ):
        stats ["updated_at"]=datetime .now (timezone .utc ).isoformat ()
        self ._cache [character_id ]=stats 
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                'INSERT OR REPLACE INTO relationships (character_id, stats, updated_at) VALUES (?, ?, ?)',
                (character_id, json.dumps(stats), stats["updated_at"])
            )
            await db.commit()

    def _apply_time_decay (self ,stats :Dict ):
        last =datetime .fromisoformat (stats ["last_interaction"])
        now =datetime .now (timezone .utc )
        elapsed =(now -last ).total_seconds ()
        days =elapsed /SECONDS_PER_DAY 
        if days >1 :
            factor =math .exp (-DECAY_RATE_PER_DAY *(days -1 ))
            stats ["avg_sentiment"]=0.5 +(stats ["avg_sentiment"]-0.5 )*factor 
            stats ["avg_depth"]=stats ["avg_depth"]*factor 

    def _analyze_sentiment(self, text: str) -> float:
        if not text or not text.strip():
            return 0.5
        compound = _VADER.polarity_scores(text)["compound"]
        return (compound + 1.0) / 2.0

    def _analyze_depth (self ,text :str )->float :
        words =set (re .sub (r'[^a-zA-Z\s]','',text .lower ()).split ())
        markers =words &DEPTH_MARKERS 
        length_score =min (len (text .split ())/30 ,1.0 )
        marker_score =min (len (markers )/3 ,1.0 )
        return length_score *0.5 +marker_score *0.5 

    async def analyze_message (self ,role :str ,content :str ,character_id :str ):
        stats =await self ._load (character_id )
        self ._apply_time_decay (stats )

        stats ["interaction_count"]+=1 
        stats ["last_interaction"]=datetime .now (timezone .utc ).isoformat ()

        if role =="user":
            word_count =len (content .split ())
            stats ["total_words_user"]+=word_count 
            sentiment =self ._analyze_sentiment (content )
            depth =self ._analyze_depth (content )
            n =stats ["interaction_count"]
            stats ["avg_sentiment"]=stats ["avg_sentiment"]+(sentiment -stats ["avg_sentiment"])/min (n ,50 )
            stats ["avg_depth"]=stats ["avg_depth"]+(depth -stats ["avg_depth"])/min (n ,50 )
        elif role =="assistant":
            stats ["total_words_assistant"]+=len (content .split ())

        await self ._save (character_id ,stats )

    async def get_stage (self ,character_id :str )->str :
        stats =await self ._load (character_id )
        return self ._calculate_stage (stats )

    def _calculate_stage (self ,stats :Dict )->str :
        best ="stranger"
        for name ,reqs in STAGES :
            if (stats ["interaction_count"]>=reqs ["interaction_count"]
            and stats ["avg_sentiment"]>=reqs ["avg_sentiment"]
            and stats ["avg_depth"]>=reqs ["avg_depth"]):
                best =name 
        return best 

    async def get_context_string (self ,character_id :str )->str :
        stats =await self ._load (character_id )
        stage =self ._calculate_stage (stats )
        lines =[
        f"Relationship stage: {stage .replace ('_',' ')}",
        f"Interactions: {stats ['interaction_count']}",
        ]

        if stage =="stranger":
            lines .append ("You are still getting to know each other. Keep the conversation light and friendly.")
        elif stage =="acquaintance":
            lines .append ("You've had a few conversations and are building rapport.")
        elif stage =="friend":
            lines .append ("You are friends. The user enjoys talking with you. Be warm and engaged.")
        elif stage =="close_friend":
            lines .append ("You are close friends. There is mutual trust and understanding. Deeper topics are welcome.")
        elif stage =="intimate":
            lines .append ("You share a deep bond. Conversations can be very personal and meaningful.")

        return "\n".join (lines )

    async def get_stats (self ,character_id :str )->Dict :
        stats =await self ._load (character_id )
        return {
        "interaction_count":stats ["interaction_count"],
        "avg_sentiment":round (stats ["avg_sentiment"],3 ),
        "avg_depth":round (stats ["avg_depth"],3 ),
        "stage":self ._calculate_stage (stats ),
        "total_words_user":stats ["total_words_user"],
        "total_words_assistant":stats ["total_words_assistant"],
        "last_interaction":stats ["last_interaction"],
        }
