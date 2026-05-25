import sqlite3 
import json 
import asyncio 
import concurrent .futures 
import threading 
import numpy as np 
import logging 
import uuid 
from typing import List ,Dict ,Optional 

logger =logging .getLogger (__name__ )

_LOCAL_EMBEDDING =None 
try :
    from sentence_transformers import SentenceTransformer 
    _LOCAL_EMBEDDING =SentenceTransformer ("all-MiniLM-L6-v2")
except ImportError :
    pass 


class Memory :
    def __init__ (self ,llm_router =None ,db_path =None ,settings =None ):
        import os 
        from k_core .paths import CONVERSATIONS_DB 
        if db_path is None :
            db_path =CONVERSATIONS_DB 
        self .llm =llm_router 
        self .settings =settings 
        os .makedirs (os .path .dirname (db_path ),exist_ok =True )
        self .conn =sqlite3 .connect (db_path ,check_same_thread =False )
        self .cursor =self .conn .cursor ()
        self ._db_cursor =self .conn .cursor ()
        self ._lock =threading .Lock ()

        self .cursor .execute ('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self .cursor .execute ('''
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                session_id TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self .cursor .execute ('''
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance REAL DEFAULT 0.5,
                source_session TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try :
            self .cursor .execute ("SELECT session_id FROM conversations LIMIT 1")
        except sqlite3 .OperationalError :
            logger .debug ("Migrating conversations table: adding session_id column")
            self .cursor .execute ("ALTER TABLE conversations ADD COLUMN session_id TEXT DEFAULT 'legacy'")
            self .conn .commit ()

        self .conn .commit ()

        self .summarizing =False 
        self ._current_session :Optional [str ]=None 
        self ._db_executor =concurrent .futures .ThreadPoolExecutor (max_workers =1 ,thread_name_prefix ="mem_db")
        self ._known_sessions :set =set ()
        self ._sync_execute ('SELECT DISTINCT session_id FROM conversations')
        for row in self .cursor .fetchall ():
            self ._known_sessions .add (row [0 ])

    async def _db_commit (self ):
        loop =asyncio .get_running_loop ()
        await loop .run_in_executor (self ._db_executor ,self .conn .commit )

    def _db_execute_sync (self ,sql ,params =None ):
        if params is None :
            return self ._db_cursor .execute (sql )
        return self ._db_cursor .execute (sql ,params )

    async def _db_execute (self ,sql ,params =None ):
        loop =asyncio .get_running_loop ()
        if params is None :
            return await loop .run_in_executor (self ._db_executor ,self ._db_cursor .execute ,sql )
        return await loop .run_in_executor (self ._db_executor ,self ._db_cursor .execute ,sql ,params )

    async def _db_executemany (self ,sql ,seq ):
        loop =asyncio .get_running_loop ()
        return await loop .run_in_executor (self ._db_executor ,self ._db_cursor .executemany ,sql ,seq )

    def _sync_execute (self ,sql ,params =None ):
        if params is None :
            return self .cursor .execute (sql )
        return self .cursor .execute (sql ,params )

    def _setting (self ,key :str ,default ):
        if self .settings :
            return self .settings .get (key ,default )
        return default 

    def start_session (self )->str :
        self ._current_session =uuid .uuid4 ().hex [:12 ]
        self ._known_sessions .add (self ._current_session )
        return self ._current_session 

    def session_exists (self ,session_id :str )->bool :
        if session_id in self ._known_sessions :
            return True 
        with self ._lock :
            row =self ._sync_execute (
            'SELECT COUNT(*) FROM conversations WHERE session_id = ?',(session_id ,)
            ).fetchone ()
        return row is not None and row [0 ]>0 

    def set_current_session (self ,session_id :str ):
        self ._current_session =session_id 

    def get_current_session (self )->str :
        if not self ._current_session :
            self ._current_session =uuid .uuid4 ().hex [:12 ]
            self ._known_sessions .add (self ._current_session )
        return self ._current_session 

    async def _get_embedding (self ,text :str )->Optional [List [float ]]:
        backend =self ._setting ("memory.embedding_backend","provider")

        if backend =="disabled":
            return None 

        if backend =="local"and _LOCAL_EMBEDDING is not None :
            try :
                emb =_LOCAL_EMBEDDING .encode (text )
                return emb .tolist ()
            except Exception as e :
                logger .debug (f"Local embedding failed: {e }")

        if backend in ("provider","local")and self .llm :
            try :
                emb =await self .llm .get_embedding (text )
                if emb :
                    return emb 
            except Exception as e :
                logger .debug (f"Provider embedding failed: {e }")

        if _LOCAL_EMBEDDING is not None :
            try :
                emb =_LOCAL_EMBEDDING .encode (text )
                return emb .tolist ()
            except Exception :
                pass 

        return None 

    async def add_turn (self ,role :str ,content :str ):
        session_id =self .get_current_session ()
        embedding_json =None 
        embedding =await self ._get_embedding (content )
        if embedding :
            embedding_json =json .dumps (embedding )

        await self ._db_execute (
        'INSERT INTO conversations (session_id, role, content, embedding) VALUES (?, ?, ?, ?)',
        (session_id ,role ,content ,embedding_json )
        )
        await self ._db_commit ()

        asyncio .create_task (self .check_and_summarize ())

    def get_sessions (self )->List [Dict ]:
        with self ._lock :
            self ._sync_execute ('''
                SELECT session_id,
                       MIN(timestamp) as started,
                       MAX(timestamp) as last_active,
                       COUNT(*) as msg_count
                FROM conversations
                GROUP BY session_id
                ORDER BY MAX(id) DESC
            ''')
            sessions =[]
            for row in self .cursor .fetchall ():
                sid ,started ,last_active ,count =row 
                self .cursor .execute (
                "SELECT content FROM conversations WHERE session_id = ? AND role = 'user' ORDER BY id ASC LIMIT 1",
                (sid ,)
                )
                preview_row =self .cursor .fetchone ()
                preview =preview_row [0 ][:80 ]if preview_row else "No messages"
                sessions .append ({
                "id":sid ,
                "started":started ,
                "last_active":last_active ,
                "message_count":count ,
                "preview":preview 
                })
        return sessions 

    def get_session_messages (self ,session_id :str )->List [Dict ]:
        with self ._lock :
            self ._sync_execute (
            'SELECT id, role, content, timestamp FROM conversations WHERE session_id = ? ORDER BY id ASC',
            (session_id ,)
            )
            return [{"id":r [0 ],"role":r [1 ],"content":r [2 ],"timestamp":r [3 ]}for r in self .cursor .fetchall ()]

    async def delete_session (self ,session_id :str )->bool :
        await self ._db_execute ('DELETE FROM conversations WHERE session_id = ?',(session_id ,))
        await self ._db_commit ()
        self ._known_sessions .discard (session_id )
        return self ._db_cursor .rowcount >0 

    def get_recent (self ,n :int =None )->List [Dict [str ,str ]]:
        if n is None :
            n =self ._setting ("memory.context_window",50 )
        session_id =self .get_current_session ()
        with self ._lock :
            self ._sync_execute (
            'SELECT id, role, content, timestamp FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?',
            (session_id ,n )
            )
            rows =self .cursor .fetchall ()
        return [{"id":row [0 ],"role":row [1 ],"content":row [2 ],"timestamp":row [3 ]}for row in reversed (rows )]

    def get_all_recent (self ,n :int =None )->List [Dict [str ,str ]]:
        if n is None :
            n =self ._setting ("memory.context_window",50 )
        session_id =self .get_current_session ()
        with self ._lock :
            self ._sync_execute (
            'SELECT id, role, content, timestamp FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?',
            (session_id ,n )
            )
            rows =self .cursor .fetchall ()
        return [{"id":row [0 ],"role":row [1 ],"content":row [2 ],"timestamp":row [3 ]}for row in reversed (rows )]

    async def delete_message (self ,msg_id :int )->bool :
        await self ._db_execute ('DELETE FROM conversations WHERE id = ?',(msg_id ,))
        await self ._db_commit ()
        return self ._db_cursor .rowcount >0 

    def get_summary (self )->str :
        with self ._lock :
            self ._sync_execute ('SELECT summary FROM summaries ORDER BY id DESC LIMIT 1')
            row =self .cursor .fetchone ()
        return row [0 ]if row else ""

    def get_session_summary (self ,session_id :str )->str :
        with self ._lock :
            self ._sync_execute (
            'SELECT summary FROM summaries WHERE session_id = ? ORDER BY id DESC LIMIT 1',
            (session_id ,)
            )
            row =self .cursor .fetchone ()
        return row [0 ]if row else ""

    async def get_relevant (self ,query :str ,top_k :int =None )->List [Dict [str ,str ]]:
        if top_k is None :
            top_k =self ._setting ("memory.retrieval_k",3 )
        if not self .llm and _LOCAL_EMBEDDING is None :
            return []

        query_emb =await self ._get_embedding (query )
        if not query_emb :
            return []

        q_vec =np .array (query_emb )
        q_norm =np .linalg .norm (q_vec )
        if q_norm ==0 :
            return []

        session_id =self .get_current_session ()

        with self ._lock :
            self ._sync_execute (
            'SELECT role, content, embedding FROM conversations WHERE embedding IS NOT NULL AND session_id = ?',
            (session_id ,)
            )
            rows =self .cursor .fetchall ()

        scored =[]
        for role ,content ,emb_str in rows :
            try :
                emb =np .array (json .loads (emb_str ))
                emb_norm =np .linalg .norm (emb )
                if emb_norm ==0 :
                    continue 
                sim =np .dot (q_vec ,emb )/(q_norm *emb_norm )
                scored .append ((sim ,role ,content ))
            except Exception as e :
                logger .debug ("Embedding similarity failed: %s",e )

        scored .sort (key =lambda x :x [0 ],reverse =True )
        return [{"role":s [1 ],"content":s [2 ]}for s in scored [:top_k ]]

    async def _prune_tool_outputs (self ,session_id :str ,max_chars :int =2000 ):
        loop =asyncio .get_running_loop ()
        rows =await loop .run_in_executor (
        self ._db_executor ,
        lambda :self ._db_cursor .execute (
        'SELECT id, content FROM conversations WHERE session_id = ? AND role = ? ORDER BY id ASC',
        (session_id ,"system")
        ).fetchall ()
        )
        for row in rows :
            msg_id ,content =row 
            if len (content )>max_chars :
                truncated =content [:max_chars ]+"\n[...truncated]"
                await loop .run_in_executor (
                self ._db_executor ,
                lambda mid =msg_id ,txt =truncated :self ._db_cursor .execute (
                'UPDATE conversations SET content = ? WHERE id = ?',(txt ,mid )
                )
                )
        if rows :
            await self ._db_commit ()

    async def check_and_summarize (self ):
        if self .summarizing or not self .llm :
            return 

        threshold =self ._setting ("memory.summarize_threshold",40 )
        keep =self ._setting ("memory.summarize_keep",15 )
        session_id =self .get_current_session ()

        with self ._lock :
            self .cursor .execute ('SELECT COUNT(*) FROM conversations WHERE session_id = ?',(session_id ,))
            row =self .cursor .fetchone ()
            count =row [0 ]if row else 0 

        if count >threshold :
            self .summarizing =True 
            try :
                loop =asyncio .get_running_loop ()

                await self ._prune_tool_outputs (session_id )

                last_compacted =self .get_session_summary_id (session_id )
                rows =await loop .run_in_executor (
                self ._db_executor ,
                lambda :self ._db_cursor .execute (
                'SELECT id, role, content FROM conversations WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?',
                (session_id ,last_compacted ,keep )
                ).fetchall ()
                )

                if not rows :
                    return 

                last_id =rows [-1 ][0 ]
                chat_log ="\n".join ([f"{r [1 ]}: {r [2 ]}"for r in rows ])

                existing =self .get_session_summary (session_id )
                context_hint =f"\nPrevious summary:\n{existing }"if existing else ""

                prompt =(
                "Analyze the following conversation history and produce a structured compaction summary. "
                "Focus on preserving actionable information: decisions, file paths, commands, user preferences, and next steps. "
                "Use these sections:\n"
                "## Goal\n## Constraints\n## Progress\n## Key Decisions\n## Next Steps\n## Critical Context\n## Relevant Files\n\n"
                f"Conversation:\n{chat_log }\n{context_hint }\n\nCompacted summary:"
                )
                summary =await self .llm .generate ([{"role":"user","content":prompt }])

                from k_core .core .plugin import get_registry as get_plugin_registry 
                summary =await get_plugin_registry ().hook_compaction (summary or "")

                if summary and not summary .startswith ("Error"):
                    await self ._db_execute (
                    'INSERT INTO summaries (summary, session_id) VALUES (?, ?)',
                    (summary ,session_id )
                    )
                    await self ._db_execute (
                    'DELETE FROM conversations WHERE id <= ? AND session_id = ? AND id > ?',
                    (last_id ,session_id ,last_compacted )
                    )
                    await self ._db_commit ()
                    logger .debug ("Structured compaction complete.")
            except Exception as e :
                logger .error (f"Compaction failed: {e }")
            finally :
                self .summarizing =False 

    def get_session_summary_id (self ,session_id :str )->int :
        with self ._lock :
            self ._sync_execute (
            'SELECT COALESCE(MAX(conversations.id), 0) FROM conversations WHERE session_id = ?',
            (session_id ,)
            )
            row =self .cursor .fetchone ()
            return row [0 ]if row else 0 

    async def extract_facts (self ,user_content :str ,assistant_content :str ):
        if not self ._setting ("memory.fact_extraction",True ):
            return 
        if not self .llm :
            return 
        prompt =(
        "Extract key facts from this exchange as a JSON array of objects. "
        "Each object has: fact (str, specific self-contained statement), "
        "category (str: 'user_info'|'preference'|'opinion'|'shared_experience'|'general'), "
        "importance (float 0.0-1.0). "
        "Only extract substantive facts, not greetings or pleasantries.\n\n"
        f"User: {user_content }\nAssistant: {assistant_content }\n\nJSON:"
        )
        try :
            result =await self .llm .generate ([{"role":"user","content":prompt }])
            if result and not result .startswith ("Error"):
                raw =result .strip ()
                if raw .startswith ("```"):
                    raw =raw .split ("\n",1 )[-1 ].rsplit ("```",1 )[0 ]
                facts =json .loads (raw )
                session_id =self .get_current_session ()
                loop =asyncio .get_running_loop ()
                await loop .run_in_executor (
                self ._db_executor ,
                lambda :self ._insert_facts_with_dedup (facts ,session_id )
                )
        except (json .JSONDecodeError ,Exception )as e :
            logger .debug (f"Fact extraction skipped: {e }")

    def _insert_facts_with_dedup (self ,facts :list ,session_id :str ):
        self ._db_cursor .execute ('SELECT fact FROM facts ORDER BY id DESC LIMIT 500')
        existing =[r [0 ].lower ()for r in self ._db_cursor .fetchall ()]
        for f in facts :
            fact_text =str (f .get ("fact",""))
            if not fact_text :
                continue 
            fact_lower =fact_text .lower ()
            fact_words =set (fact_lower .split ())
            is_duplicate =False 
            for existing_fact in existing :
                existing_words =set (existing_fact .split ())
                common =len (fact_words &existing_words )
                total =len (fact_words |existing_words )
                similarity =common /max (total ,1 )
                if similarity >0.65 :
                    is_duplicate =True 
                    break 
            if not is_duplicate :
                self ._db_cursor .execute (
                'INSERT INTO facts (fact, category, importance, source_session) VALUES (?, ?, ?, ?)',
                (fact_text ,str (f .get ("category","general")),
                min (1.0 ,max (0.0 ,float (f .get ("importance",0.5 )))),session_id )
                )
                existing .append (fact_lower )
        self .conn .commit ()

    async def delete_fact (self ,fact_id :int ):
        await self ._db_execute ('DELETE FROM facts WHERE id = ?',(fact_id ,))
        await self ._db_commit ()

    async def add_fact (self ,fact :str ,category :str ="general",importance :float =0.5 ):
        session_id =self .get_current_session ()
        await self ._db_execute (
        'INSERT INTO facts (fact, category, importance, source_session) VALUES (?, ?, ?, ?)',
        (fact ,category ,min (1.0 ,max (0.0 ,importance )),session_id )
        )
        await self ._db_commit ()

    def get_facts (self ,category :str =None ,min_importance :float =0.0 ,limit :int =50 ):
        with self ._lock :
            if category :
                self ._sync_execute (
                'SELECT id, fact, category, importance, timestamp FROM facts WHERE category = ? AND importance >= ? ORDER BY importance DESC, timestamp DESC LIMIT ?',
                (category ,min_importance ,limit )
                )
            else :
                self ._sync_execute (
                'SELECT id, fact, category, importance, timestamp FROM facts WHERE importance >= ? ORDER BY importance DESC, timestamp DESC LIMIT ?',
                (min_importance ,limit )
                )
            return [{"id":r [0 ],"fact":r [1 ],"category":r [2 ],"importance":r [3 ],"timestamp":r [4 ]}for r in self .cursor .fetchall ()]

    async def get_relevant_facts (self ,query :str ,top_k :int =5 ):
        query_words =set (query .lower ().split ())
        with self ._lock :
            self ._sync_execute ('SELECT id, fact, category, importance FROM facts ORDER BY importance DESC LIMIT 200')
            rows =self .cursor .fetchall ()
        scored =[]
        for fid ,fact ,cat ,imp in rows :
            fact_words =set (fact .lower ().split ())
            common =len (query_words &fact_words )
            total =len (query_words |fact_words )
            keyword_sim =common /max (total ,1 )
            score =keyword_sim *0.4 +float (imp )*0.6 
            scored .append ((score ,fid ,fact ,cat ,imp ))
        scored .sort (key =lambda x :x [0 ],reverse =True )
        return [{"id":s [1 ],"fact":s [2 ],"category":s [3 ],"importance":s [4 ]}for s in scored [:top_k ]]

    async def clear (self ):
        loop =asyncio .get_running_loop ()
        await loop .run_in_executor (
        self ._db_executor ,
        lambda :[
        self ._db_cursor .execute ('DELETE FROM conversations'),
        self ._db_cursor .execute ('DELETE FROM summaries'),
        self ._db_cursor .execute ('DELETE FROM facts'),
        self .conn .commit ()
        ]
        )
