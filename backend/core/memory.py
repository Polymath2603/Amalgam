import sqlite3 
import json 
import asyncio 
import numpy as np 
import logging 
import uuid 
from typing import List ,Dict ,Optional 

logger =logging .getLogger (__name__ )

class Memory :
    def __init__ (self ,llm_router =None ,db_path ="user_data/conversations.db"):
        import os 
        self .llm =llm_router 
        os .makedirs (os .path .dirname (db_path ),exist_ok =True )
        self .conn =sqlite3 .connect (db_path ,check_same_thread =False )
        self .cursor =self .conn .cursor ()


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
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')


        try :
            self .cursor .execute ("SELECT session_id FROM conversations LIMIT 1")
        except sqlite3 .OperationalError :
            logger .info ("Migrating conversations table: adding session_id column")
            self .cursor .execute ("ALTER TABLE conversations ADD COLUMN session_id TEXT DEFAULT 'legacy'")
            self .conn .commit ()

        self .conn .commit ()

        self .summarizing =False 
        self ._current_session :Optional [str ]=None 

    def start_session (self )->str :
        """Start a new conversation session and return its ID."""
        self ._current_session =uuid .uuid4 ().hex [:12 ]
        return self ._current_session 

    def get_current_session (self )->str :
        """Get or create the current session ID."""
        if not self ._current_session :
            self ._current_session =uuid .uuid4 ().hex [:12 ]
        return self ._current_session 

    async def add_turn (self ,role :str ,content :str ):
        session_id =self .get_current_session ()
        embedding_json =None 
        if self .llm :
            embedding =await self .llm .get_embedding (content )
            if embedding :
                embedding_json =json .dumps (embedding )

        self .cursor .execute (
        'INSERT INTO conversations (session_id, role, content, embedding) VALUES (?, ?, ?, ?)',
        (session_id ,role ,content ,embedding_json )
        )
        self .conn .commit ()


        asyncio .create_task (self .check_and_summarize ())

    def get_sessions (self )->List [Dict ]:
        """Get all sessions with preview text and message count."""
        self .cursor .execute ('''
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
        """Get all messages for a specific session."""
        self .cursor .execute (
        'SELECT id, role, content, timestamp FROM conversations WHERE session_id = ? ORDER BY id ASC',
        (session_id ,)
        )
        return [{"id":r [0 ],"role":r [1 ],"content":r [2 ],"timestamp":r [3 ]}for r in self .cursor .fetchall ()]

    def delete_session (self ,session_id :str )->bool :
        """Delete all messages in a session."""
        self .cursor .execute ('DELETE FROM conversations WHERE session_id = ?',(session_id ,))
        self .conn .commit ()
        return self .cursor .rowcount >0 

    def get_recent (self ,n :int =50 )->List [Dict [str ,str ]]:
        """Get recent messages from current session for context building."""
        session_id =self .get_current_session ()
        self .cursor .execute (
        'SELECT id, role, content, timestamp FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?',
        (session_id ,n )
        )
        rows =self .cursor .fetchall ()
        return [{"id":row [0 ],"role":row [1 ],"content":row [2 ],"timestamp":row [3 ]}for row in reversed (rows )]

    def get_all_recent (self ,n :int =50 )->List [Dict [str ,str ]]:
        """Get recent messages across all sessions (for context fallback)."""
        self .cursor .execute ('SELECT id, role, content, timestamp FROM conversations ORDER BY id DESC LIMIT ?',(n ,))
        rows =self .cursor .fetchall ()
        return [{"id":row [0 ],"role":row [1 ],"content":row [2 ],"timestamp":row [3 ]}for row in reversed (rows )]

    def delete_message (self ,msg_id :int )->bool :
        self .cursor .execute ('DELETE FROM conversations WHERE id = ?',(msg_id ,))
        self .conn .commit ()
        return self .cursor .rowcount >0 

    def get_summary (self )->str :
        self .cursor .execute ('SELECT summary FROM summaries ORDER BY id DESC LIMIT 1')
        row =self .cursor .fetchone ()
        return row [0 ]if row else ""

    async def get_relevant (self ,query :str ,top_k :int =3 )->List [Dict [str ,str ]]:
        if not self .llm :return []

        query_emb =await self .llm .get_embedding (query )
        if not query_emb :return []

        q_vec =np .array (query_emb )
        session_id =self .get_current_session ()

        self .cursor .execute (
        'SELECT role, content, embedding FROM conversations WHERE embedding IS NOT NULL AND session_id = ?',
        (session_id ,)
        )
        rows =self .cursor .fetchall ()

        scored =[]
        for role ,content ,emb_str in rows :
            try :
                emb =np .array (json .loads (emb_str ))
                sim =np .dot (q_vec ,emb )/(np .linalg .norm (q_vec )*np .linalg .norm (emb ))
                scored .append ((sim ,role ,content ))
            except Exception :
                pass 

        scored .sort (key =lambda x :x [0 ],reverse =True )
        return [{"role":s [1 ],"content":s [2 ]}for s in scored [:top_k ]]

    async def check_and_summarize (self ):
        if self .summarizing or not self .llm :
            return 

        session_id =self .get_current_session ()
        self .cursor .execute ('SELECT COUNT(*) FROM conversations WHERE session_id = ?',(session_id ,))
        count =self .cursor .fetchone ()[0 ]

        if count >30 :
            self .summarizing =True 
            try :
                logger .info ("Auto-summarizing older memories...")

                self .cursor .execute (
                'SELECT id, role, content FROM conversations WHERE session_id = ? ORDER BY id ASC LIMIT 20',
                (session_id ,)
                )
                rows =self .cursor .fetchall ()

                if not rows :
                    return 

                last_id =rows [-1 ][0 ]
                chat_log ="\n".join ([f"{r [1 ]}: {r [2 ]}"for r in rows ])

                prompt =f"Summarize the following conversation history concisely:\n{chat_log }\n\nSummary:"
                summary =await self .llm .generate ([{"role":"user","content":prompt }])

                if summary and not summary .startswith ("Error"):
                    existing =self .get_summary ()
                    if existing :
                        prompt =f"Combine these two summaries into one coherent overview:\n1. {existing }\n2. {summary }\n\nCombined Summary:"
                        summary =await self .llm .generate ([{"role":"user","content":prompt }])

                    self .cursor .execute ('INSERT INTO summaries (summary) VALUES (?)',(summary ,))
                    self .cursor .execute ('DELETE FROM conversations WHERE id <= ? AND session_id = ?',(last_id ,session_id ))
                    self .conn .commit ()
                    logger .info ("Summarization complete.")
            except Exception as e :
                logger .error (f"Summarization failed: {e }")
            finally :
                self .summarizing =False 

    def clear (self ):
        self .cursor .execute ('DELETE FROM conversations')
        self .cursor .execute ('DELETE FROM summaries')
        self .conn .commit ()
