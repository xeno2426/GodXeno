"""
migrate_to_pg.py — One-time migration: GodXeno JSON files → Neon Postgres

Usage (run from PythonAnywhere Bash console):
    cd ~/mysite
    DATABASE_URL="postgresql://neondb_owner:YOUR_PASS@ep-floral-field-a13croew-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require" python3 ~/migrate_to_pg.py

Make sure db.py is in ~/mysite/ first.
"""

import os, sys, json
from datetime import datetime

# ── point to your mysite directory so we can import db ──────────────────────
MYSITE = os.path.join(os.path.dirname(__file__), "mysite")
sys.path.insert(0, MYSITE)

DATA_DIR = os.path.join(MYSITE, "data")

import db

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def parse_ts(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def run():
    print("🚀 Initialising DB schema...")
    db.init_db()

    # ── Users ────────────────────────────────────────────────────────────────
    users_json = load_json(os.path.join(DATA_DIR, "users.json"), {})
    print(f"\n👤 Migrating {len(users_json)} users...")
    for uname, info in users_json.items():
        db.create_user(
            username     = uname,
            password_hash= info.get("password_hash", ""),
            email        = info.get("email", ""),
            bio          = info.get("bio", ""),
            avatar       = info.get("avatar", ""),
            recovery     = info.get("recovery", ""),
        )
        updates = {}
        if info.get("last_seen"):
            updates["last_seen"] = parse_ts(info["last_seen"])
        if info.get("typing_to"):
            updates["typing_to"] = info["typing_to"]
        if info.get("typing_ts"):
            updates["typing_ts"] = parse_ts(info["typing_ts"])
        if info.get("typing_group"):
            updates["typing_group"] = info["typing_group"]
        if info.get("typing_group_ts"):
            updates["typing_group_ts"] = parse_ts(info["typing_group_ts"])
        if updates:
            db.update_user(uname, **updates)

        # friends
        for friend in info.get("friends", []):
            if friend in users_json:
                db.add_friend(uname, friend)

        # unread
        for from_user, count in info.get("unread", {}).items():
            if count and count > 0:
                for _ in range(int(count)):
                    db.increment_unread(uname, from_user)

        print(f"  ✓ {uname}")

    # ── Direct Messages ───────────────────────────────────────────────────────
    print("\n💬 Migrating direct messages...")
    import glob
    chat_files = glob.glob(os.path.join(DATA_DIR, "chat_*__*.json"))
    total_msgs = 0
    for path in chat_files:
        msgs = load_json(path, [])
        for m in msgs:
            sender    = m.get("from") or m.get("sender", "")
            recipient = m.get("to")   or m.get("recipient", "")
            if not sender or not recipient:
                continue
            text     = m.get("text", "")
            ftype    = m.get("ftype", "text")
            filename = m.get("filename", "")
            url      = m.get("url", "")
            db.send_message(sender, recipient, text, ftype, filename, url)
            total_msgs += 1
    print(f"  ✓ {total_msgs} messages migrated")

    # ── Groups ────────────────────────────────────────────────────────────────
    print("\n👥 Migrating groups...")
    groups_json = load_json(os.path.join(DATA_DIR, "groups.json"), {})
    for gid, g in groups_json.items():
        db.create_group(
            group_id = gid,
            name     = g.get("name", "Group"),
            owner    = g.get("owner", ""),
            avatar   = g.get("avatar", ""),
        )
        for member in g.get("members", []):
            db.add_group_member(gid, member)

        # group messages
        gpath = os.path.join(DATA_DIR, f"group_{gid}.json")
        gmsgs = load_json(gpath, [])
        for m in gmsgs:
            sender = m.get("from") or m.get("sender", "")
            if not sender:
                continue
            db.send_group_message(
                group_id = gid,
                sender   = sender,
                text     = m.get("text", ""),
                ftype    = m.get("ftype", "text"),
                filename = m.get("filename", ""),
                url      = m.get("url", ""),
            )
        print(f"  ✓ group '{g.get('name')}' ({len(gmsgs)} messages)")

    # ── Notes ─────────────────────────────────────────────────────────────────
    print("\n📝 Migrating notes...")
    notes_dir = os.path.join(DATA_DIR, "notes")
    total_notes = 0
    if os.path.isdir(notes_dir):
        for fname in os.listdir(notes_dir):
            if not fname.endswith("_notes.json"):
                continue
            uname = fname.replace("_notes.json", "")
            notes = load_json(os.path.join(notes_dir, fname), [])
            for n in notes:
                db.add_note(uname, n.get("title",""), n.get("body",""), n.get("image",""))
                total_notes += 1
    # also legacy notes_username.json
    for fname in os.listdir(DATA_DIR):
        if fname.startswith("notes_") and fname.endswith(".json"):
            uname = fname[6:-5]
            notes = load_json(os.path.join(DATA_DIR, fname), [])
            for n in notes:
                db.add_note(uname, n.get("title",""), n.get("body",""), n.get("image",""))
                total_notes += 1
    print(f"  ✓ {total_notes} notes migrated")

    # ── Stories ───────────────────────────────────────────────────────────────
    print("\n📸 Migrating stories...")
    stories_file = os.path.join(MYSITE, "stories.json")
    stories_json = load_json(stories_file, {})
    total_stories = 0
    for uname, story_list in stories_json.items():
        for s in story_list:
            file_url   = s.get("file", "")
            media_type = s.get("type", "image")
            if file_url:
                db.add_story(uname, file_url, media_type)
                total_stories += 1
    print(f"  ✓ {total_stories} stories migrated")

    print("\n✅ Migration complete! All data is now in Neon Postgres.")
    print("   Next step: upload db.py to ~/mysite/ on PythonAnywhere")
    print("   Then set DATABASE_URL in PythonAnywhere environment variables")
    print("   Then update app.py imports to use db instead of JSON helpers")

if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        print("❌ DATABASE_URL env var not set!")
        print('   Run with: DATABASE_URL="postgresql://..." python3 migrate_to_pg.py')
        sys.exit(1)
    run()
