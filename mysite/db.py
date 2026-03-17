import os, json
import pg8000.native
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    u = urlparse(DATABASE_URL)
    return pg8000.native.Connection(
        user=u.username, password=u.password,
        host=u.hostname, port=u.port or 5432,
        database=u.path.lstrip("/"), ssl_context=True
    )

def query(sql, params=(), one=False):
    conn = get_conn()
    try:
        rows = conn.run(sql, *params)
        cols = [c["name"] for c in conn.columns]
        result = [dict(zip(cols, row)) for row in rows]
        return result[0] if one and result else (result if not one else None)
    finally:
        conn.close()

def execute(sql, params=()):
    conn = get_conn()
    try:
        conn.run(sql, *params)
    finally:
        conn.close()

def init_db():
    stmts = [
        """CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password_hash TEXT DEFAULT '',
            email TEXT DEFAULT '', bio TEXT DEFAULT '', avatar TEXT DEFAULT '',
            recovery TEXT DEFAULT '', last_seen TIMESTAMP, typing_to TEXT DEFAULT '',
            typing_ts TIMESTAMP, typing_group TEXT DEFAULT '',
            typing_group_ts TIMESTAMP, created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS friends (
            user1 TEXT NOT NULL, user2 TEXT NOT NULL, PRIMARY KEY (user1, user2))""",
        """CREATE TABLE IF NOT EXISTS friend_requests (
            from_user TEXT NOT NULL, to_user TEXT NOT NULL,
            PRIMARY KEY (from_user, to_user))""",
        """CREATE TABLE IF NOT EXISTS unread (
            username TEXT NOT NULL, from_user TEXT NOT NULL,
            count INTEGER DEFAULT 0, PRIMARY KEY (username, from_user))""",
        """CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
            text TEXT DEFAULT '', ftype TEXT DEFAULT 'text',
            filename TEXT DEFAULT '', url TEXT DEFAULT '',
            seen BOOLEAN DEFAULT FALSE, reply_to INTEGER,
            reactions TEXT DEFAULT '{}', deleted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL,
            avatar TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS group_members (
            group_id TEXT NOT NULL, username TEXT NOT NULL,
            PRIMARY KEY (group_id, username))""",
        """CREATE TABLE IF NOT EXISTS group_messages (
            id SERIAL PRIMARY KEY, group_id TEXT NOT NULL, sender TEXT NOT NULL,
            text TEXT DEFAULT '', ftype TEXT DEFAULT 'text',
            filename TEXT DEFAULT '', url TEXT DEFAULT '',
            reply_to INTEGER, reactions TEXT DEFAULT '{}',
            deleted BOOLEAN DEFAULT FALSE, seen_by TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY, username TEXT NOT NULL,
            title TEXT DEFAULT '', body TEXT DEFAULT '',
            image TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS stories (
            id SERIAL PRIMARY KEY, username TEXT NOT NULL,
            file TEXT NOT NULL, media_type TEXT DEFAULT 'image',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS otps (
            username TEXT PRIMARY KEY, otp TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL)""",
    ]
    conn = get_conn()
    try:
        for s in stmts:
            conn.run(s)
        print("DB schema ready")
    finally:
        conn.close()

def get_user(u): return query("SELECT * FROM users WHERE username=:1",(u,),one=True)
def user_exists(u): return bool(query("SELECT 1 FROM users WHERE username=:1",(u,),one=True))

def create_user(username,password_hash,email="",bio="",avatar="",recovery=""):
    execute("""INSERT INTO users(username,password_hash,email,bio,avatar,recovery)
               VALUES(:1,:2,:3,:4,:5,:6) ON CONFLICT(username) DO NOTHING""",
            (username,password_hash,email,bio,avatar,recovery))

def update_user(username,**kwargs):
    allowed={"password_hash","email","bio","avatar","recovery",
             "last_seen","typing_to","typing_ts","typing_group","typing_group_ts"}
    conn=get_conn()
    try:
        for k,v in kwargs.items():
            if k in allowed:
                conn.run(f"UPDATE users SET {k}=:1 WHERE username=:2",v,username)
    finally:
        conn.close()

def load_users():
    rows=query("SELECT * FROM users")
    out={}
    for r in rows:
        u=r["username"]; out[u]=dict(r)
        out[u]["friends"]=get_friends(u); out[u]["unread"]=get_unread_dict(u)
    return out

def get_friends(username):
    rows=query("SELECT CASE WHEN user1=:1 THEN user2 ELSE user1 END AS friend FROM friends WHERE user1=:1 OR user2=:1",(username,))
    return [r["friend"] for r in rows]

def are_friends(u1,u2):
    return bool(query("SELECT 1 FROM friends WHERE (user1=:1 AND user2=:2) OR (user1=:2 AND user2=:1)",(u1,u2),one=True))

def add_friend(u1,u2):
    a,b=sorted([u1,u2])
    execute("INSERT INTO friends(user1,user2) VALUES(:1,:2) ON CONFLICT DO NOTHING",(a,b))

def remove_friend(u1,u2):
    a,b=sorted([u1,u2])
    execute("DELETE FROM friends WHERE user1=:1 AND user2=:2",(a,b))

def send_request(f,t): execute("INSERT INTO friend_requests(from_user,to_user) VALUES(:1,:2) ON CONFLICT DO NOTHING",(f,t))
def cancel_request(f,t): execute("DELETE FROM friend_requests WHERE from_user=:1 AND to_user=:2",(f,t))
def get_pending_in(u): return [r["from_user"] for r in query("SELECT from_user FROM friend_requests WHERE to_user=:1",(u,))]
def get_pending_out(u): return [r["to_user"] for r in query("SELECT to_user FROM friend_requests WHERE from_user=:1",(u,))]
def accept_request(f,t): cancel_request(f,t); add_friend(f,t)
def reject_request(f,t): cancel_request(f,t)

def get_unread_dict(u): return {r["from_user"]:r["count"] for r in query("SELECT from_user,count FROM unread WHERE username=:1",(u,))}
def count_unread(u):
    r=query("SELECT COALESCE(SUM(count),0) AS total FROM unread WHERE username=:1",(u,),one=True)
    return int(r["total"]) if r else 0
def increment_unread(u,f): execute("INSERT INTO unread(username,from_user,count) VALUES(:1,:2,1) ON CONFLICT(username,from_user) DO UPDATE SET count=unread.count+1",(u,f))
def reset_unread(u,f): execute("UPDATE unread SET count=0 WHERE username=:1 AND from_user=:2",(u,f))

def load_chat(u1,u2):
    rows=query("SELECT * FROM messages WHERE (sender=:1 AND recipient=:2) OR (sender=:2 AND recipient=:1) ORDER BY created_at ASC",(u1,u2))
    for r in rows:
        if isinstance(r.get("reactions"),str): r["reactions"]=json.loads(r["reactions"])
    return rows

def send_message(sender,recipient,text="",ftype="text",filename="",url="",reply_to=None):
    conn=get_conn()
    try:
        rows=conn.run("INSERT INTO messages(sender,recipient,text,ftype,filename,url,reply_to) VALUES(:1,:2,:3,:4,:5,:6,:7) RETURNING id",sender,recipient,text,ftype,filename,url,reply_to)
        return rows[0][0]
    finally:
        conn.close()

def mark_seen(u1,u2): execute("UPDATE messages SET seen=TRUE WHERE sender=:1 AND recipient=:2 AND seen=FALSE",(u1,u2))
def delete_message(mid): execute("UPDATE messages SET deleted=TRUE,text='[deleted]' WHERE id=:1",(mid,))

def load_groups():
    out={}
    for g in query("SELECT * FROM groups"):
        gid=g["group_id"]; d=dict(g); d["members"]=get_group_members(gid); out[gid]=d
    return out

def get_group(gid):
    g=query("SELECT * FROM groups WHERE group_id=:1",(gid,),one=True)
    if not g: return None
    g=dict(g); g["members"]=get_group_members(gid); return g

def create_group(gid,name,owner,avatar=""):
    execute("INSERT INTO groups(group_id,name,owner,avatar) VALUES(:1,:2,:3,:4) ON CONFLICT DO NOTHING",(gid,name,owner,avatar))
    add_group_member(gid,owner)

def delete_group(gid):
    execute("DELETE FROM group_members WHERE group_id=:1",(gid,))
    execute("DELETE FROM group_messages WHERE group_id=:1",(gid,))
    execute("DELETE FROM groups WHERE group_id=:1",(gid,))

def get_group_members(gid): return [r["username"] for r in query("SELECT username FROM group_members WHERE group_id=:1",(gid,))]
def add_group_member(gid,u): execute("INSERT INTO group_members(group_id,username) VALUES(:1,:2) ON CONFLICT DO NOTHING",(gid,u))
def remove_group_member(gid,u): execute("DELETE FROM group_members WHERE group_id=:1 AND username=:2",(gid,u))

def user_groups(username):
    rows=query("SELECT g.* FROM groups g JOIN group_members gm ON g.group_id=gm.group_id WHERE gm.username=:1 ORDER BY g.created_at",(username,))
    out=[]
    for g in rows:
        d=dict(g); d["members"]=get_group_members(g["group_id"]); out.append(d)
    return out

def load_group_chat(gid):
    rows=query("SELECT * FROM group_messages WHERE group_id=:1 ORDER BY created_at ASC",(gid,))
    for r in rows:
        if isinstance(r.get("reactions"),str): r["reactions"]=json.loads(r["reactions"])
        if isinstance(r.get("seen_by"),str): r["seen_by"]=json.loads(r["seen_by"])
    return rows

def send_group_message(gid,sender,text="",ftype="text",filename="",url="",reply_to=None):
    conn=get_conn()
    try:
        rows=conn.run("INSERT INTO group_messages(group_id,sender,text,ftype,filename,url,reply_to,seen_by) VALUES(:1,:2,:3,:4,:5,:6,:7,:8) RETURNING id",gid,sender,text,ftype,filename,url,reply_to,json.dumps([sender]))
        return rows[0][0]
    finally:
        conn.close()

def mark_group_seen(gid,username):
    rows=query("SELECT id,seen_by FROM group_messages WHERE group_id=:1",(gid,))
    for row in rows:
        seen=json.loads(row["seen_by"]) if isinstance(row["seen_by"],str) else row["seen_by"]
        if username not in seen:
            seen.append(username)
            execute("UPDATE group_messages SET seen_by=:1 WHERE id=:2",(json.dumps(seen),row["id"]))

def load_notes(u): return query("SELECT * FROM notes WHERE username=:1 ORDER BY created_at DESC",(u,))
def add_note(u,title,body,image=""): execute("INSERT INTO notes(username,title,body,image) VALUES(:1,:2,:3,:4)",(u,title,body,image))
def update_note(nid,u,title,body): execute("UPDATE notes SET title=:1,body=:2 WHERE id=:3 AND username=:4",(title,body,nid,u))
def delete_note(nid,u): execute("DELETE FROM notes WHERE id=:1 AND username=:2",(nid,u))

STORY_TTL_HOURS=16
def load_stories():
    out={}
    for r in query("SELECT * FROM stories WHERE created_at > NOW() - INTERVAL '16 hours' ORDER BY username,created_at ASC"):
        out.setdefault(r["username"],[]).append(dict(r))
    return out
def add_story(u,file_url,media_type="image"): execute("INSERT INTO stories(username,file,media_type) VALUES(:1,:2,:3)",(u,file_url,media_type))
def delete_story(sid,u): execute("DELETE FROM stories WHERE id=:1 AND username=:2",(sid,u))

def set_otp(u,otp,exp): execute("INSERT INTO otps(username,otp,expires_at) VALUES(:1,:2,:3) ON CONFLICT(username) DO UPDATE SET otp=:2,expires_at=:3",(u,otp,exp))
def get_otp(u): return query("SELECT * FROM otps WHERE username=:1",(u,),one=True)
def delete_otp(u): execute("DELETE FROM otps WHERE username=:1",(u,))
