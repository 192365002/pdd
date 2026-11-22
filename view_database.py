"""
DeepVerify / SocialShield - Database Inspector
Reads and displays records from the active persistent database.
"""
import sqlite3
import json
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), 'socialshield.db')

def view_database():
    if not os.path.exists(DB_PATH):
        print(f"Database file not found at: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("=" * 60)
    print("   DEEPVERIFY / SOCIALSHIELD PERSISTENT DATABASE")
    print(f"   Location: {DB_PATH}")
    print("=" * 60)

    # 1. Collection Counts
    counts = cursor.execute(
        "SELECT collection, count(*) as cnt FROM collections GROUP BY collection"
    ).fetchall()
    print("\n[+] COLLECTIONS SUMMARY:")
    for row in counts:
        print(f"  • {row['collection']:<15}: {row['cnt']} records")

    # 2. Users
    print("\n[+] REGISTERED USERS:")
    users = cursor.execute(
        "SELECT id, data FROM collections WHERE collection='users'"
    ).fetchall()
    for row in users:
        d = json.loads(row['data'])
        print(f"  • Email: {d.get('email', 'N/A'):<30} | Role: {d.get('role', 'user'):<8} | Name: {d.get('name', 'N/A')}")

    # 3. Recent Scans
    print("\n[+] RECENT 10 SCANS:")
    scans = cursor.execute(
        "SELECT id, data FROM collections WHERE collection='scans' ORDER BY rowid DESC LIMIT 10"
    ).fetchall()
    for row in scans:
        d = json.loads(row['data'])
        stype = d.get('type') or d.get('scan_type') or 'unknown'
        verdict = d.get('verdict') or d.get('prediction') or d.get('status') or 'unknown'
        user = d.get('user_email') or d.get('user_id') or 'guest'
        time = d.get('timestamp') or d.get('created_at') or 'N/A'
        print(f"  • [{stype.upper():<6}] Verdict: {str(verdict):<24} | User: {str(user):<20} | Time: {str(time)[:19]}")

    # 4. Threats
    print("\n[+] ACTIVE THREATS:")
    threats = cursor.execute(
        "SELECT id, data FROM collections WHERE collection='threats'"
    ).fetchall()
    for row in threats:
        d = json.loads(row['data'])
        print(f"  • Type: {d.get('type', 'N/A'):<15} | Severity: {d.get('severity', 'N/A'):<8} | Desc: {d.get('description', '')[:40]}")

    print("\n" + "=" * 60)

if __name__ == '__main__':
    view_database()
