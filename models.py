import os
import datetime
import logging
import sqlite3
import json
import threading
from bson import ObjectId

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Try real MongoDB first, fall back to SQLite
# ─────────────────────────────────────────────
_db_instance = None
_use_sqlite = False
_sqlite_lock = threading.Lock()


# ══════════════════════════════════════════════
# SQLITE REAL PERSISTENT BACKEND
# ══════════════════════════════════════════════
SQLITE_PATH = os.path.join(os.path.dirname(__file__), 'socialshield.db')


def _get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_sqlite():
    with _get_sqlite_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS collections (
            id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_col ON collections(collection)")
        conn.commit()
    logger.info(f"SQLite persistent database ready: {SQLITE_PATH}")


class SQLiteCollection:
    """Real persistent SQLite-backed collection with MongoDB-compatible API."""

    def __init__(self, name):
        self.name = name

    def _new_id(self):
        import uuid
        return str(uuid.uuid4())

    def _decode(self, row):
        d = json.loads(row['data'])
        d['_id'] = row['id']
        return d

    def _match(self, doc, fq):
        if not fq:
            return True
        for k, v in fq.items():
            if k == '$or':
                if not any(self._match(doc, sub) for sub in v):
                    return False
            elif k == '$and':
                if not all(self._match(doc, sub) for sub in v):
                    return False
            elif k == '_id':
                if str(doc.get('_id', '')) != str(v):
                    return False
            elif isinstance(v, dict):
                dv = doc.get(k)
                for op, ov in v.items():
                    if op == '$in' and dv not in ov:
                        return False
                    elif op == '$nin' and dv in ov:
                        return False
                    elif op == '$ne' and dv == ov:
                        return False
                    elif op == '$eq' and dv != ov:
                        return False
                    elif op == '$exists':
                        exists = k in doc and doc[k] is not None
                        if exists != bool(ov):
                            return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    def _all_docs(self):
        with _get_sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT id, data FROM collections WHERE collection=?", (self.name,)
            ).fetchall()
        docs = []
        for row in rows:
            d = json.loads(row['data'])
            d['_id'] = row['id']
            docs.append(d)
        return docs

    def insert_one(self, document):
        doc = document.copy()
        doc_id = str(doc.pop('_id', None) or self._new_id())
        # Serialize datetime objects
        for k, v in doc.items():
            if isinstance(v, datetime.datetime):
                doc[k] = v.isoformat()
        with _sqlite_lock:
            with _get_sqlite_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO collections(id, collection, data) VALUES(?,?,?)",
                    (doc_id, self.name, json.dumps(doc))
                )
                conn.commit()
        return type('R', (), {'inserted_id': doc_id})()

    def find_one(self, fq=None, projection=None, *a, **kw):
        for doc in self._all_docs():
            if self._match(doc, fq or {}):
                return doc
        return None

    def find(self, fq=None, projection=None, *a, **kw):
        results = [d for d in self._all_docs() if self._match(d, fq or {})]

        class Cursor:
            def __init__(self, items):
                self.items = items
            def __iter__(self):
                return iter(self.items)
            def sort(self, key, direction=-1):
                self.items.sort(
                    key=lambda x: str(x.get(key, '')), reverse=(direction == -1)
                )
                return self
            def limit(self, n):
                self.items = self.items[:n]
                return self

        return Cursor(results)

    def update_one(self, fq, update):
        doc = self.find_one(fq)
        if not doc:
            return type('R', (), {'modified_count': 0, 'matched_count': 0})()
        doc_id = str(doc.pop('_id'))
        for op, data in update.items():
            if op == '$set':
                for k, v in data.items():
                    doc[k] = v.isoformat() if isinstance(v, datetime.datetime) else v
            elif op == '$push':
                for k, v in data.items():
                    doc.setdefault(k, []).append(v)
        with _sqlite_lock:
            with _get_sqlite_conn() as conn:
                conn.execute(
                    "UPDATE collections SET data=? WHERE id=? AND collection=?",
                    (json.dumps(doc), doc_id, self.name)
                )
                conn.commit()
        return type('R', (), {'modified_count': 1, 'matched_count': 1})()

    def update_many(self, fq, update):
        modified = 0
        for doc in self._all_docs():
            if self._match(doc, fq):
                doc_id = str(doc.pop('_id'))
                for op, data in update.items():
                    if op == '$set':
                        for k, v in data.items():
                            doc[k] = v.isoformat() if isinstance(v, datetime.datetime) else v
                with _sqlite_lock:
                    with _get_sqlite_conn() as conn:
                        conn.execute(
                            "UPDATE collections SET data=? WHERE id=? AND collection=?",
                            (json.dumps(doc), doc_id, self.name)
                        )
                        conn.commit()
                modified += 1
        return type('R', (), {'modified_count': modified, 'matched_count': modified})()

    def delete_one(self, fq):
        doc = self.find_one(fq)
        if doc:
            with _sqlite_lock:
                with _get_sqlite_conn() as conn:
                    conn.execute(
                        "DELETE FROM collections WHERE id=? AND collection=?",
                        (str(doc['_id']), self.name)
                    )
                    conn.commit()
            return type('R', (), {'deleted_count': 1})()
        return type('R', (), {'deleted_count': 0})()

    def count_documents(self, fq=None):
        with _get_sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT data FROM collections WHERE collection=?", (self.name,)
            ).fetchall()
        count = 0
        for row in rows:
            d = json.loads(row['data'])
            if self._match(d, fq or {}):
                count += 1
        return count


class SQLiteDatabase:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = SQLiteCollection(name)
        return self._cols[name]


# ══════════════════════════════════════════════
# DB INIT — Try MongoDB, fall back to SQLite
# ══════════════════════════════════════════════

def init_db():
    global _db_instance, _use_sqlite

    mongo_uri = os.environ.get('MONGO_URI') or os.environ.get('MONGODB_URI')

    if mongo_uri and '<username>' not in mongo_uri and '<password>' not in mongo_uri:
        try:
            from pymongo import MongoClient
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=4000)
            client.server_info()
            _db_instance = client['socialshield']
            _use_sqlite = False
            logger.info("Connected to MongoDB successfully.")
            return _db_instance
        except Exception as e:
            logger.warning(f"MongoDB unavailable ({e}). Using SQLite persistent storage.")

    # SQLite persistent fallback
    _init_sqlite()
    _db_instance = SQLiteDatabase()
    _use_sqlite = True
    return _db_instance


def get_db():
    global _db_instance
    if _db_instance is None:
        return init_db()
    return _db_instance
