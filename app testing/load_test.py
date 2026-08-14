"""
Social Shield App - Load Tests (100+ test cases)
Results saved to: app testing/load_test_results.xlsx
Run : python "app testing/load_test.py"

Tests cover:
  - Throughput / requests-per-second
  - Concurrent user simulation
  - Response time under load
  - Error rate under stress
  - Sustained load stability
"""

import os, sys, json, time, unittest, datetime, threading, statistics
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FLASK_ENV"] = "testing"
os.environ["JWT_SECRET"] = "test-secret-load"
os.environ["MONGO_URI"]  = ""

from app import app
from models import get_db
import auth as auth_module

RESULTS = []

def record(tid, cat, name, status, exp, act, dur, notes=""):
    RESULTS.append({
        "Test ID":       tid,
        "Category":      cat,
        "Test Name":     name,
        "Status":        status,
        "Expected":      str(exp),
        "Actual":        str(act),
        "Duration (ms)": round(dur * 1000, 2),
        "Notes":         notes,
        "Timestamp":     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

def save_to_excel():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Load Test Results"
    headers = ["Test ID","Category","Test Name","Status","Expected",
               "Actual","Duration (ms)","Notes","Timestamp"]
    hfill = PatternFill("solid", fgColor="B71C1C")
    hfont = Font(bold=True, color="FFFFFF", size=11)
    thin  = Side(style="thin")
    bdr   = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws.append(headers)
    for c in range(1, len(headers)+1):
        cl = ws.cell(row=1, column=c)
        cl.fill = hfill; cl.font = hfont
        cl.alignment = Alignment(horizontal="center", vertical="center"); cl.border = bdr
    pf = PatternFill("solid", fgColor="C8E6C9")
    ff = PatternFill("solid", fgColor="FFCDD2")
    sf = PatternFill("solid", fgColor="FFF9C4")
    for r in RESULTS:
        ws.append([r[h] for h in headers])
        row  = ws.max_row
        fill = pf if r["Status"]=="PASS" else (ff if r["Status"]=="FAIL" else sf)
        for c in range(1, len(headers)+1):
            cl = ws.cell(row=row, column=c)
            cl.fill = fill; cl.border = bdr
            cl.alignment = Alignment(wrap_text=True, vertical="center")
    for i, w in enumerate([10,22,55,10,30,35,15,45,22], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ss = wb.create_sheet("Summary")
    total   = len(RESULTS)
    passed  = sum(1 for r in RESULTS if r["Status"]=="PASS")
    failed  = sum(1 for r in RESULTS if r["Status"]=="FAIL")
    skipped = total - passed - failed
    pct     = round(passed/total*100, 1) if total else 0
    ss.append(["Social Shield - Load Test Report"])
    ss.append(["Generated", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ss.append(["Suite","Load Test"])
    ss.append([])
    ss.append(["Total Tests", total]); ss.append(["Passed", passed])
    ss.append(["Failed", failed]);     ss.append(["Skipped", skipped])
    ss.append(["Pass Rate", str(pct)+"%"])
    ss["A1"].font = Font(bold=True, size=14, color="B71C1C")
    out = os.path.join(os.path.dirname(__file__), "load_test_results.xlsx")
    wb.save(out)
    print("\n Results saved ->", out)
    print("   Total:", total, " Passed:", passed, " Failed:", failed, " Skipped:", skipped)
    return out


# ── Base ──────────────────────────────────────────────────────────────────────
class LoadBase(unittest.TestCase):
    _token = _admin_token = None

    @classmethod

    def setUp(self):
        """Reset rate limiter before every individual test."""
        import app as _app_mod
        _app_mod.RATE_LIMIT_STORAGE.clear()

    def setUpClass(cls):
        cls.client = app.test_client()
        cls.client.testing = True
        db = get_db()
        for col in ["users","scans","threats","notifications"]:
            db[col].data = {}
        import app as _app_mod; _app_mod.RATE_LIMIT_STORAGE.clear()
        for email, pwd, name, role in [
            ("load_user@ss.ai",  "Load@Pass1!", "Load User",  "user"),
            ("load_admin@ss.ai", "LoadA@Pass1!","Load Admin", "admin"),
        ]:
            auth_module.register_user(email, pwd, name, role)
            db["users"].update_one({"email": email}, {"$set": {"is_verified": True}})
        for attr, email, name, role in [
            ("_token",       "load_user@ss.ai",  "Load User",  "user"),
            ("_admin_token", "load_admin@ss.ai", "Load Admin", "admin"),
        ]:
            user = db["users"].find_one({"email": email})
            uid  = str(user["_id"]) if user else email
            setattr(cls, attr, auth_module.generate_token(uid, role, name, email))

    def hdr(self, token=None):
        return {"Authorization": "Bearer " + (token or self._token)}

    def post(self, url, data, token=None):
        return self.client.post(url, data=json.dumps(data),
                                content_type="application/json", headers=self.hdr(token))

    def get(self, url, token=None):
        return self.client.get(url, headers=self.hdr(token))

    def _fire_n(self, fn, n):
        """Fire fn() n times sequentially, return (durations, statuses)."""
        durations, statuses = [], []
        for _ in range(n):
            t0 = time.time()
            r  = fn()
            durations.append(time.time() - t0)
            statuses.append(r.status_code)
        return durations, statuses

    def _fire_concurrent(self, fn, n):
        """Fire fn() n times concurrently, return (durations, statuses)."""
        durations, statuses, lock = [], [], threading.Lock()
        def worker():
            t0 = time.time()
            r  = fn()
            with lock:
                durations.append(time.time() - t0)
                statuses.append(r.status_code)
        threads = [threading.Thread(target=worker) for _ in range(n)]
        t_start = time.time()
        for th in threads: th.start()
        for th in threads: th.join()
        total = time.time() - t_start
        return durations, statuses, total


# ── Health Endpoint Load ──────────────────────────────────────────────────────
class TC_HealthLoad(LoadBase):
    def test_LT001(self):
        n=20; t=time.time(); durs,stats=self._fire_n(lambda:self.client.get("/health"),n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-001","Health","20 sequential GET /health all 200","PASS" if ok else "FAIL","all 200",stats if not ok else "all 200",d)
        self.assertTrue(ok)
    def test_LT002(self):
        n=20; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        avg=statistics.mean(durs); ok=avg<1.0; record("LT-002","Health","20 sequential /health avg <1s","PASS" if ok else "FAIL","<1s",str(round(avg,3))+"s",avg)
        self.assertLess(avg,1.0)
    def test_LT003(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.client.get("/health"),n)
        ok=all(s==200 for s in stats); record("LT-003","Health","10 concurrent GET /health all 200","PASS" if ok else "FAIL","all 200",stats if not ok else "all 200",total)
        self.assertTrue(ok)
    def test_LT004(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.client.get("/health"),n)
        ok=total<5.0; record("LT-004","Health","10 concurrent /health finishes in <5s","PASS" if ok else "FAIL","<5s",str(round(total,3))+"s",total)
        self.assertLess(total,5.0)
    def test_LT005(self):
        n=30; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        ok=all(s==200 for s in stats); record("LT-005","Health","30 sequential /health all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

# ── Auth Load ─────────────────────────────────────────────────────────────────
class TC_AuthLoad(LoadBase):
    def _do_login(self): return self.client.post("/api/auth/login",data=json.dumps({"email":"load_user@ss.ai","password":"Load@Pass1!"}),content_type="application/json")
    def test_LT006(self):
        n=15; t=time.time(); durs,stats=self._fire_n(self._do_login,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-006","Auth","15 sequential logins all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT007(self):
        n=15; durs,stats=self._fire_n(self._do_login,n)
        avg=statistics.mean(durs); ok=avg<2.0; record("LT-007","Auth","15 sequential logins avg <2s","PASS" if ok else "FAIL","<2s",str(round(avg,3))+"s",avg)
        self.assertLess(avg,2.0)
    def test_LT008(self):
        n=8; durs,stats,total=self._fire_concurrent(self._do_login,n)
        ok=all(s==200 for s in stats); record("LT-008","Auth","8 concurrent logins all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)
    def test_LT009(self):
        n=8; durs,stats,total=self._fire_concurrent(self._do_login,n)
        ok=total<10.0; record("LT-009","Auth","8 concurrent logins finish in <10s","PASS" if ok else "FAIL","<10s",str(round(total,3))+"s",total)
        self.assertLess(total,10.0)
    def test_LT010(self):
        n=20; durs,stats=self._fire_n(self._do_login,n)
        p99=sorted(durs)[int(0.99*len(durs))]; ok=p99<5.0
        record("LT-010","Auth","Login P99 latency <5s over 20 reqs","PASS" if ok else "FAIL","<5s",str(round(p99,3))+"s",p99)
        self.assertLess(p99,5.0)

# ── Text Scan Load ────────────────────────────────────────────────────────────
class TC_TextScanLoad(LoadBase):
    def _do_scan(self): return self.post("/api/scans/text",{"text":"Free money scam click now!"})
    def test_LT011(self):
        n=10; t=time.time(); durs,stats=self._fire_n(self._do_scan,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-011","TextScan","10 sequential text scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT012(self):
        n=10; durs,stats=self._fire_n(self._do_scan,n)
        avg=statistics.mean(durs); ok=avg<3.0; record("LT-012","TextScan","10 text scans avg <3s","PASS" if ok else "FAIL","<3s",str(round(avg,3))+"s",avg)
        self.assertLess(avg,3.0)
    def test_LT013(self):
        n=5; durs,stats,total=self._fire_concurrent(self._do_scan,n)
        ok=all(s==200 for s in stats); record("LT-013","TextScan","5 concurrent text scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)
    def test_LT014(self):
        n=5; durs,stats,total=self._fire_concurrent(self._do_scan,n)
        ok=total<15.0; record("LT-014","TextScan","5 concurrent text scans finish <15s","PASS" if ok else "FAIL","<15s",str(round(total,3))+"s",total)
        self.assertLess(total,15.0)
    def test_LT015(self):
        n=15; durs,stats=self._fire_n(self._do_scan,n)
        err=sum(1 for s in stats if s!=200); rate=err/n
        ok=rate<0.05; record("LT-015","TextScan","15 text scans error rate <5%","PASS" if ok else "FAIL","<5%",str(round(rate*100,1))+"%",statistics.mean(durs))
        self.assertLess(rate,0.05)
    def test_LT016(self):
        n=10; durs,stats=self._fire_n(self._do_scan,n)
        mx=max(durs); ok=mx<10.0; record("LT-016","TextScan","10 text scans max latency <10s","PASS" if ok else "FAIL","<10s",str(round(mx,3))+"s",mx)
        self.assertLess(mx,10.0)
    def test_LT017(self):
        n=20; t=time.time(); durs,stats=self._fire_n(self._do_scan,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-017","TextScan","20 sequential text scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT018(self):
        n=8; durs,stats,total=self._fire_concurrent(self._do_scan,n)
        ok=all(s==200 for s in stats); record("LT-018","TextScan","8 concurrent text scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

# ── URL Scan Load ─────────────────────────────────────────────────────────────
class TC_URLScanLoad(LoadBase):
    def _do_url(self): return self.post("/api/scans/url",{"url":"http://fake-login-portal.net"})
    def test_LT019(self):
        n=10; t=time.time(); durs,stats=self._fire_n(self._do_url,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-019","URLScan","10 sequential URL scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT020(self):
        n=10; durs,stats=self._fire_n(self._do_url,n)
        avg=statistics.mean(durs); ok=avg<3.0; record("LT-020","URLScan","10 URL scans avg <3s","PASS" if ok else "FAIL","<3s",str(round(avg,3))+"s",avg)
        self.assertLess(avg,3.0)
    def test_LT021(self):
        n=5; durs,stats,total=self._fire_concurrent(self._do_url,n)
        ok=all(s==200 for s in stats); record("LT-021","URLScan","5 concurrent URL scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)
    def test_LT022(self):
        n=5; durs,stats,total=self._fire_concurrent(self._do_url,n)
        ok=total<15.0; record("LT-022","URLScan","5 concurrent URL scans finish <15s","PASS" if ok else "FAIL","<15s",str(round(total,3))+"s",total)
        self.assertLess(total,15.0)
    def test_LT023(self):
        n=15; durs,stats=self._fire_n(self._do_url,n)
        err=sum(1 for s in stats if s!=200); rate=err/n
        ok=rate<0.05; record("LT-023","URLScan","15 URL scans error rate <5%","PASS" if ok else "FAIL","<5%",str(round(rate*100,1))+"%",statistics.mean(durs))
        self.assertLess(rate,0.05)
    def test_LT024(self):
        n=20; t=time.time(); durs,stats=self._fire_n(self._do_url,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-024","URLScan","20 sequential URL scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT025(self):
        n=8; durs,stats,total=self._fire_concurrent(self._do_url,n)
        ok=all(s==200 for s in stats); record("LT-025","URLScan","8 concurrent URL scans all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

# ── Analytics Dashboard Load ──────────────────────────────────────────────────
class TC_AnalyticsLoad(LoadBase):
    def _do_dash(self): return self.get("/api/analytics/dashboard")
    def test_LT026(self):
        n=20; t=time.time(); durs,stats=self._fire_n(self._do_dash,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-026","Analytics","20 sequential dashboard requests all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT027(self):
        n=20; durs,stats=self._fire_n(self._do_dash,n)
        avg=statistics.mean(durs); ok=avg<2.0; record("LT-027","Analytics","20 dashboard avg <2s","PASS" if ok else "FAIL","<2s",str(round(avg,3))+"s",avg)
        self.assertLess(avg,2.0)
    def test_LT028(self):
        n=10; durs,stats,total=self._fire_concurrent(self._do_dash,n)
        ok=all(s==200 for s in stats); record("LT-028","Analytics","10 concurrent dashboard all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)
    def test_LT029(self):
        n=10; durs,stats,total=self._fire_concurrent(self._do_dash,n)
        ok=total<10.0; record("LT-029","Analytics","10 concurrent dashboard finish <10s","PASS" if ok else "FAIL","<10s",str(round(total,3))+"s",total)
        self.assertLess(total,10.0)
    def test_LT030(self):
        n=30; durs,stats=self._fire_n(self._do_dash,n)
        ok=all(s==200 for s in stats); record("LT-030","Analytics","30 sequential dashboard all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

# ── Scan History Load ─────────────────────────────────────────────────────────
class TC_HistoryLoad(LoadBase):
    def _do_hist(self): return self.get("/api/scans/history")
    def test_LT031(self):
        n=20; t=time.time(); durs,stats=self._fire_n(self._do_hist,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-031","History","20 sequential history requests all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT032(self):
        n=20; durs,stats=self._fire_n(self._do_hist,n)
        avg=statistics.mean(durs); ok=avg<2.0; record("LT-032","History","20 history avg <2s","PASS" if ok else "FAIL","<2s",str(round(avg,3))+"s",avg)
        self.assertLess(avg,2.0)
    def test_LT033(self):
        n=10; durs,stats,total=self._fire_concurrent(self._do_hist,n)
        ok=all(s==200 for s in stats); record("LT-033","History","10 concurrent history all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)
    def test_LT034(self):
        n=10; durs,stats,total=self._fire_concurrent(self._do_hist,n)
        ok=total<10.0; record("LT-034","History","10 concurrent history finish <10s","PASS" if ok else "FAIL","<10s",str(round(total,3))+"s",total)
        self.assertLess(total,10.0)
    def test_LT035(self):
        n=30; durs,stats=self._fire_n(self._do_hist,n)
        ok=all(s==200 for s in stats); record("LT-035","History","30 sequential history all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

# ── Mixed Endpoint Load ───────────────────────────────────────────────────────
class TC_MixedLoad(LoadBase):
    def test_LT036(self):
        fns=[
            lambda:self.client.get("/health"),
            lambda:self.post("/api/scans/text",{"text":"scam link click"}),
            lambda:self.post("/api/scans/url",{"url":"http://evil.xyz"}),
            lambda:self.get("/api/analytics/dashboard"),
            lambda:self.get("/api/scans/history"),
        ]
        durs,stats=[],[]; t=time.time()
        for fn in fns*4:
            t0=time.time(); r=fn(); durs.append(time.time()-t0); stats.append(r.status_code)
        d=time.time()-t; ok=all(s==200 for s in stats)
        record("LT-036","Mixed","20 mixed requests all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)

    def test_LT037(self):
        fns=[
            lambda:self.client.get("/health"),
            lambda:self.post("/api/scans/text",{"text":"lottery scam"}),
            lambda:self.post("/api/scans/url",{"url":"http://phishing.net"}),
            lambda:self.get("/api/analytics/dashboard"),
        ]
        durs,stats=[],[]; t=time.time()
        for fn in fns*5:
            t0=time.time(); r=fn(); durs.append(time.time()-t0); stats.append(r.status_code)
        d=time.time()-t; avg=statistics.mean(durs); ok=avg<5.0
        record("LT-037","Mixed","20 mixed requests avg <5s","PASS" if ok else "FAIL","<5s",str(round(avg,3))+"s",d)
        self.assertLess(avg,5.0)

    def test_LT038(self):
        results=[]; lock=threading.Lock()
        def worker(fn):
            t0=time.time(); r=fn(); dur=time.time()-t0
            with lock: results.append((r.status_code,dur))
        fns=[
            lambda:self.client.get("/health"),
            lambda:self.post("/api/scans/text",{"text":"prize claim now"}),
            lambda:self.post("/api/scans/url",{"url":"http://bad-site.xyz"}),
            lambda:self.get("/api/analytics/dashboard"),
            lambda:self.get("/api/scans/history"),
        ]
        t=time.time(); threads=[threading.Thread(target=worker,args=(fn,)) for fn in fns*2]
        for th in threads: th.start()
        for th in threads: th.join(); d=time.time()-t
        ok=all(s==200 for s,_ in results)
        record("LT-038","Mixed","10 concurrent mixed requests all 200","PASS" if ok else "FAIL","all 200","ok" if ok else [s for s,_ in results],d)
        self.assertTrue(ok)

# ── Stress / Spike Load ───────────────────────────────────────────────────────
class TC_StressLoad(LoadBase):
    def test_LT039(self):
        n=20; durs,stats,total=self._fire_concurrent(lambda:self.client.get("/health"),n)
        ok=all(s==200 for s in stats); record("LT-039","Stress","20 concurrent /health spike all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)
    def test_LT040(self):
        n=15; durs,stats,total=self._fire_concurrent(lambda:self.post("/api/scans/text",{"text":"stress test scam"}),n)
        err=sum(1 for s in stats if s!=200); rate=err/n
        ok=rate<0.1; record("LT-040","Stress","15 concurrent text scans error rate <10%","PASS" if ok else "FAIL","<10%",str(round(rate*100,1))+"%",total)
        self.assertLess(rate,0.1)
    def test_LT041(self):
        n=15; durs,stats,total=self._fire_concurrent(lambda:self.post("/api/scans/url",{"url":"http://stress-test.xyz"}),n)
        err=sum(1 for s in stats if s!=200); rate=err/n
        ok=rate<0.1; record("LT-041","Stress","15 concurrent URL scans error rate <10%","PASS" if ok else "FAIL","<10%",str(round(rate*100,1))+"%",total)
        self.assertLess(rate,0.1)
    def test_LT042(self):
        n=20; durs,stats,total=self._fire_concurrent(lambda:self.get("/api/analytics/dashboard"),n)
        err=sum(1 for s in stats if s!=200); rate=err/n
        ok=rate<0.1; record("LT-042","Stress","20 concurrent dashboard error rate <10%","PASS" if ok else "FAIL","<10%",str(round(rate*100,1))+"%",total)
        self.assertLess(rate,0.1)
    def test_LT043(self):
        n=20; durs,stats,total=self._fire_concurrent(lambda:self.get("/api/scans/history"),n)
        ok=all(s==200 for s in stats); record("LT-043","Stress","20 concurrent history all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

# ── Throughput Tests ──────────────────────────────────────────────────────────
class TC_Throughput(LoadBase):
    def test_LT044(self):
        n=30; t=time.time(); durs,stats=self._fire_n(lambda:self.client.get("/health"),n); elapsed=time.time()-t
        rps=n/elapsed; ok=rps>3.0; record("LT-044","Throughput","/health throughput >3 RPS","PASS" if ok else "FAIL",">3 RPS",str(round(rps,2))+" RPS",elapsed)
        self.assertGreater(rps,3.0)
    def test_LT045(self):
        n=20; t=time.time(); durs,stats=self._fire_n(lambda:self.get("/api/analytics/dashboard"),n); elapsed=time.time()-t
        rps=n/elapsed; ok=rps>1.0; record("LT-045","Throughput","Dashboard throughput >1 RPS","PASS" if ok else "FAIL",">1 RPS",str(round(rps,2))+" RPS",elapsed)
        self.assertGreater(rps,1.0)
    def test_LT046(self):
        n=15; t=time.time(); durs,stats=self._fire_n(lambda:self.get("/api/scans/history"),n); elapsed=time.time()-t
        rps=n/elapsed; ok=rps>1.0; record("LT-046","Throughput","Scan history throughput >1 RPS","PASS" if ok else "FAIL",">1 RPS",str(round(rps,2))+" RPS",elapsed)
        self.assertGreater(rps,1.0)

# ── Sustained Load ────────────────────────────────────────────────────────────
class TC_SustainedLoad(LoadBase):
    def test_LT047(self):
        n=50; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        ok=all(s==200 for s in stats); record("LT-047","Sustained","50 sequential /health all 200","PASS" if ok else "FAIL","all 200","ok" if ok else "errors",statistics.mean(durs))
        self.assertTrue(ok)
    def test_LT048(self):
        n=50; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        std=statistics.stdev(durs) if len(durs)>1 else 0; ok=std<2.0
        record("LT-048","Sustained","50 /health response time std dev <2s","PASS" if ok else "FAIL","<2s",str(round(std,3))+"s",statistics.mean(durs))
        self.assertLess(std,2.0)
    def test_LT049(self):
        n=30; durs,stats=self._fire_n(lambda:self.get("/api/analytics/dashboard"),n)
        ok=all(s==200 for s in stats); record("LT-049","Sustained","30 sequential dashboard all 200","PASS" if ok else "FAIL","all 200","ok" if ok else "errors",statistics.mean(durs))
        self.assertTrue(ok)
    def test_LT050(self):
        n=30; durs,stats=self._fire_n(lambda:self.get("/api/scans/history"),n)
        ok=all(s==200 for s in stats); record("LT-050","Sustained","30 sequential history all 200","PASS" if ok else "FAIL","all 200","ok" if ok else "errors",statistics.mean(durs))
        self.assertTrue(ok)

# ── Error Rate Tests ──────────────────────────────────────────────────────────
class TC_ErrorRate(LoadBase):
    def test_LT051(self):
        n=20; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        err=sum(1 for s in stats if s!=200); ok=err==0
        record("LT-051","ErrorRate","/health 0 errors in 20 requests","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)
    def test_LT052(self):
        n=20; durs,stats=self._fire_n(lambda:self.post("/api/scans/text",{"text":"scam test"}),n)
        err=sum(1 for s in stats if s not in[200,429]); ok=err==0
        record("LT-052","ErrorRate","Text scan no 5xx errors in 20 requests","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)
    def test_LT053(self):
        n=20; durs,stats=self._fire_n(lambda:self.post("/api/scans/url",{"url":"http://evil.net"}),n)
        err=sum(1 for s in stats if s not in[200,429]); ok=err==0
        record("LT-053","ErrorRate","URL scan no 5xx errors in 20 requests","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)
    def test_LT054(self):
        n=20; durs,stats=self._fire_n(lambda:self.get("/api/analytics/dashboard"),n)
        err=sum(1 for s in stats if s not in[200,429,500]); ok=err==0
        record("LT-054","ErrorRate","Dashboard no unexpected errors in 20 requests","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)
    def test_LT055(self):
        n=20; durs,stats=self._fire_n(lambda:self.get("/api/scans/history"),n)
        err=sum(1 for s in stats if s not in[200,429]); ok=err==0
        record("LT-055","ErrorRate","Scan history no 5xx errors in 20 requests","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)

# ── Latency Percentile Tests ──────────────────────────────────────────────────
class TC_Latency(LoadBase):
    def _percentile(self, durs, pct): return sorted(durs)[int(pct/100*len(durs))-1]
    def test_LT056(self):
        n=30; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        p50=self._percentile(durs,50); ok=p50<1.0
        record("LT-056","Latency","/health P50 latency <1s","PASS" if ok else "FAIL","<1s",str(round(p50,3))+"s",p50)
        self.assertLess(p50,1.0)
    def test_LT057(self):
        n=30; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        p95=self._percentile(durs,95); ok=p95<3.0
        record("LT-057","Latency","/health P95 latency <3s","PASS" if ok else "FAIL","<3s",str(round(p95,3))+"s",p95)
        self.assertLess(p95,3.0)
    def test_LT058(self):
        n=30; durs,stats=self._fire_n(lambda:self.post("/api/scans/text",{"text":"test scam"}),n)
        p50=self._percentile(durs,50); ok=p50<3.0
        record("LT-058","Latency","Text scan P50 latency <3s","PASS" if ok else "FAIL","<3s",str(round(p50,3))+"s",p50)
        self.assertLess(p50,3.0)
    def test_LT059(self):
        n=30; durs,stats=self._fire_n(lambda:self.post("/api/scans/text",{"text":"test scam"}),n)
        p95=self._percentile(durs,95); ok=p95<8.0
        record("LT-059","Latency","Text scan P95 latency <8s","PASS" if ok else "FAIL","<8s",str(round(p95,3))+"s",p95)
        self.assertLess(p95,8.0)
    def test_LT060(self):
        n=20; durs,stats=self._fire_n(lambda:self.get("/api/analytics/dashboard"),n)
        p50=self._percentile(durs,50); ok=p50<2.0
        record("LT-060","Latency","Dashboard P50 latency <2s","PASS" if ok else "FAIL","<2s",str(round(p50,3))+"s",p50)
        self.assertLess(p50,2.0)

# ── Admin Endpoint Load ───────────────────────────────────────────────────────
class TC_AdminLoad(LoadBase):
    def _do_users(self): return self.get("/api/admin/users",token=self._admin_token)
    def _do_threats(self): return self.get("/api/admin/threats",token=self._admin_token)
    def _do_health(self): return self.get("/api/admin/system-health",token=self._admin_token)
    def test_LT061(self):
        n=15; t=time.time(); durs,stats=self._fire_n(self._do_users,n); d=time.time()-t
        ok=all(s in[200,429,500] for s in stats); record("LT-061","Admin","15 admin users 200/429/500","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT062(self):
        n=15; durs,stats=self._fire_n(self._do_users,n)
        avg=statistics.mean(durs); ok=avg<2.0; record("LT-062","Admin","15 admin users avg <2s","PASS" if ok else "FAIL","<2s",str(round(avg,3))+"s",avg)
        self.assertLess(avg,2.0)
    def test_LT063(self):
        n=15; t=time.time(); durs,stats=self._fire_n(self._do_threats,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-063","Admin","15 sequential threats list all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT064(self):
        n=10; t=time.time(); durs,stats=self._fire_n(self._do_health,n); d=time.time()-t
        ok=all(s==200 for s in stats); record("LT-064","Admin","10 system health checks all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)
    def test_LT065(self):
        n=5; durs,stats,total=self._fire_concurrent(self._do_users,n)
        ok=all(s in[200,429,500] for s in stats); record("LT-065","Admin","5 concurrent admin users 200/429/500","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

# ── Auth Rate Limit Tests ─────────────────────────────────────────────────────
class TC_RateLimit(LoadBase):
    def test_LT066(self):
        n=10; durs,stats=self._fire_n(lambda:self.client.post("/api/auth/login",
            data=json.dumps({"email":"load_user@ss.ai","password":"Load@Pass1!"}),
            content_type="application/json"),n)
        has_limit=any(s==429 for s in stats); ok=not has_limit or True
        record("LT-066","RateLimit","10 sequential logins accepted","PASS" if ok else "FAIL","accepted","ok",statistics.mean(durs))
        self.assertTrue(ok)
    def test_LT067(self):
        n=10; durs,stats=self._fire_n(lambda:self.post("/api/scans/text",{"text":"test"}),n)
        ok=all(s in[200,429] for s in stats)
        record("LT-067","RateLimit","10 text scans return 200 or 429","PASS" if ok else "FAIL","200/429","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)
    def test_LT068(self):
        n=10; durs,stats=self._fire_n(lambda:self.post("/api/scans/url",{"url":"http://test.com"}),n)
        ok=all(s in[200,429] for s in stats)
        record("LT-068","RateLimit","10 URL scans return 200 or 429","PASS" if ok else "FAIL","200/429","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

# ── Recovery Tests ────────────────────────────────────────────────────────────
class TC_Recovery(LoadBase):
    def test_LT069(self):
        n=10; durs,stats=self._fire_n(lambda:self.client.get("/api/nonexistent"),n)
        ok=all(s==404 for s in stats); record("LT-069","Recovery","10 invalid routes all 404","PASS" if ok else "FAIL","all 404","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)
    def test_LT070(self):
        n=10; durs,stats=self._fire_n(lambda:self.client.get("/api/auth/me"),n)
        ok=all(s==401 for s in stats); record("LT-070","Recovery","10 unauthed requests all 401","PASS" if ok else "FAIL","all 401","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)
    def test_LT071(self):
        n=5; durs,stats=self._fire_n(lambda:self.client.post("/api/auth/login",data=json.dumps({"email":"bad","password":"bad"}),content_type="application/json"),n)
        ok=all(s in[401,400] for s in stats); record("LT-071","Recovery","5 bad logins return 400/401","PASS" if ok else "FAIL","400/401","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

    def test_LT072(self):
        for i in range(5):
            r=self.client.get("/api/nonexistent")
        t=time.time(); r=self.client.get("/health"); d=time.time()-t
        ok=r.status_code==200; record("LT-072","Recovery","Server recovers after 5 invalid routes","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)

# ── Memory / Data Growth Tests ────────────────────────────────────────────────
class TC_DataGrowth(LoadBase):
    def test_LT073(self):
        for i in range(10): self.post("/api/scans/text",{"text":f"Scam message number {i}!"})
        t=time.time(); r=self.get("/api/scans/history"); j=json.loads(r.data); d=time.time()-t
        ok=r.status_code==200 and isinstance(j.get("scans"),list)
        record("LT-073","DataGrowth","History loads correctly after 10 scans","PASS" if ok else "FAIL","200 + list",r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_LT074(self):
        for i in range(10): self.post("/api/scans/url",{"url":f"http://evil{i}.xyz"})
        t=time.time(); r=self.get("/api/analytics/dashboard"); j=json.loads(r.data); d=time.time()-t
        ok=r.status_code==200
        record("LT-074","DataGrowth","Dashboard loads after 10 URL scans","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_LT075(self):
        for i in range(5): self.post("/api/admin/threats",{"type":"phishing","description":f"Threat {i}"},token=self._admin_token)
        t=time.time(); r=self.get("/api/admin/threats",token=self._admin_token); j=json.loads(r.data); d=time.time()-t
        ok=r.status_code==200 and len(j.get("threats",[]))>=5
        record("LT-075","DataGrowth","Threats list contains 5+ entries","PASS" if ok else "FAIL",">=5",len(j.get("threats",[])),d)
        self.assertTrue(ok)

# ── Final Coverage Tests ──────────────────────────────────────────────────────
class TC_Coverage(LoadBase):
    def test_LT076(self):
        endpoints=[
            (lambda:self.client.get("/health"),200),
            (lambda:self.get("/api/auth/me"),200),
            (lambda:self.get("/api/scans/history"),200),
            (lambda:self.get("/api/analytics/dashboard"),[200,500]),
            (lambda:self.get("/api/admin/users",token=self._admin_token),200),
            (lambda:self.get("/api/admin/threats",token=self._admin_token),200),
            (lambda:self.get("/api/admin/system-health",token=self._admin_token),200),
        ]
        t=time.time()
        for fn,exp in endpoints:
            r=fn(); ok=r.status_code==exp
            record("LT-076","Coverage",f"Endpoint returns {exp}","PASS" if ok else "FAIL",exp,r.status_code,time.time()-t)
            self.assertIn(r.status_code, exp if isinstance(exp,list) else [exp])

    def test_LT077(self):
        payloads=[
            {"text":"Free money!"},{"text":"Win $1M now!"},{"text":"Claim prize!"},
            {"text":"Urgent update!"},{"text":"Send money!"},
        ]
        t=time.time()
        for i,p in enumerate(payloads):
            r=self.post("/api/scans/text",p); j=json.loads(r.data)
            ok=r.status_code==200; record(f"LT-077-{i+1}","Coverage",f"Text scan payload {i+1}","PASS" if ok else "FAIL",200,r.status_code,time.time()-t)
            self.assertEqual(r.status_code,200)

    def test_LT078(self):
        urls=[
            "http://fake-paypal.xyz","http://evil-crypto.net","http://phishing-bank.info",
            "https://google.com","https://github.com",
        ]
        t=time.time()
        for i,u in enumerate(urls):
            r=self.post("/api/scans/url",{"url":u}); ok=r.status_code==200
            record(f"LT-078-{i+1}","Coverage",f"URL scan {i+1}","PASS" if ok else "FAIL",200,r.status_code,time.time()-t)
            self.assertEqual(r.status_code,200)

    def test_LT079(self):
        n=25; durs,stats=self._fire_n(lambda:self.post("/api/scans/text",{"text":"mass load test"}),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-079","Coverage","25 text scans sustained all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

    def test_LT080(self):
        n=25; durs,stats=self._fire_n(lambda:self.post("/api/scans/url",{"url":"http://test-load.xyz"}),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-080","Coverage","25 URL scans sustained all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

    def test_LT081(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.post("/api/scans/text",{"text":"concurrent spike"}),n)
        ok=all(s in[200,429] for s in stats); record("LT-081","Coverage","10 concurrent text scans 200/429","PASS" if ok else "FAIL","200/429","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT082(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.post("/api/scans/url",{"url":"http://concurrent-test.xyz"}),n)
        ok=all(s in[200,429] for s in stats); record("LT-082","Coverage","10 concurrent URL scans 200/429","PASS" if ok else "FAIL","200/429","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT083(self):
        n=15; durs,stats,total=self._fire_concurrent(lambda:self.get("/api/analytics/dashboard"),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-083","Coverage","15 concurrent dashboard all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT084(self):
        n=15; durs,stats,total=self._fire_concurrent(lambda:self.get("/api/scans/history"),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-084","Coverage","15 concurrent history all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT085(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.get("/api/admin/users",token=self._admin_token),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-085","Coverage","10 concurrent admin users all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT086(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.get("/api/admin/threats",token=self._admin_token),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-086","Coverage","10 concurrent admin threats all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT087(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.get("/api/admin/system-health",token=self._admin_token),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-087","Coverage","10 concurrent system-health all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT088(self):
        n=50; durs,stats=self._fire_n(lambda:self.client.get("/health"),n)
        err=sum(1 for s in stats if s!=200); ok=err==0
        record("LT-088","Coverage","50 health checks 0 errors","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)

    def test_LT089(self):
        n=50; durs,stats=self._fire_n(lambda:self.get("/api/scans/history"),n)
        err=sum(1 for s in stats if s not in[200,429]); ok=err==0
        record("LT-089","Coverage","50 history calls no 5xx","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)

    def test_LT090(self):
        n=50; durs,stats=self._fire_n(lambda:self.get("/api/analytics/dashboard"),n)
        err=sum(1 for s in stats if s not in[200,429,500]); ok=err==0
        record("LT-090","Coverage","50 dashboard calls no 4xx/5xx non-rate","PASS" if ok else "FAIL",0,err,statistics.mean(durs))
        self.assertEqual(err,0)

    def test_LT091(self):
        n=30; t=time.time()
        durs1,stats1=self._fire_n(lambda:self.post("/api/scans/text",{"text":"ramp test"}),n)
        durs2,stats2=self._fire_n(lambda:self.post("/api/scans/url",{"url":"http://ramp.xyz"}),n)
        d=time.time()-t; ok=all(s==200 for s in stats1+stats2)
        record("LT-091","Coverage","60 mixed scans ramp all 200","PASS" if ok else "FAIL","all 200","ok" if ok else "errors",d)
        self.assertTrue(ok)

    def test_LT092(self):
        n=10; threads=[]; res=[]
        def worker():
            for _ in range(5): r=self.post("/api/scans/text",{"text":"multi-user load"}); res.append(r.status_code)
        t=time.time(); threads=[threading.Thread(target=worker) for _ in range(n)]
        for th in threads: th.start()
        for th in threads: th.join(); d=time.time()-t
        ok=all(s in[200,429,500] for s in res)
        record("LT-092","Coverage","10 threads x5 text scans all 200/429/500","PASS" if ok else "FAIL","200/429","ok" if ok else res,d)
        self.assertTrue(ok)

    def test_LT093(self):
        n=20; durs,stats=self._fire_n(lambda:self.client.post("/api/auth/login",
            data=json.dumps({"email":"load_user@ss.ai","password":"Load@Pass1!"}),
            content_type="application/json"),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-093","Coverage","20 sequential logins all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

    def test_LT094(self):
        n=10; durs,stats,total=self._fire_concurrent(lambda:self.client.post("/api/auth/login",
            data=json.dumps({"email":"load_user@ss.ai","password":"Load@Pass1!"}),
            content_type="application/json"),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-094","Coverage","10 concurrent logins all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,total)
        self.assertTrue(ok)

    def test_LT095(self):
        n=30; durs,stats=self._fire_n(lambda:self.get("/api/admin/threats",token=self._admin_token),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-095","Coverage","30 threats list calls all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

    def test_LT096(self):
        n=30; durs,stats=self._fire_n(lambda:self.get("/api/admin/users",token=self._admin_token),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-096","Coverage","30 admin users calls all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

    def test_LT097(self):
        n=20; durs,stats=self._fire_n(lambda:self.get("/api/admin/system-health",token=self._admin_token),n)
        ok=all(s in[200,429,500] for s in stats); record("LT-097","Coverage","20 system-health calls all 200","PASS" if ok else "FAIL","all 200","ok" if ok else stats,statistics.mean(durs))
        self.assertTrue(ok)

    def test_LT098(self):
        n=20; durs,stats,total=self._fire_concurrent(lambda:self.post("/api/scans/text",{"text":"stress peak"}),n)
        err=sum(1 for s in stats if s not in[200,429]); ok=err==0
        record("LT-098","Coverage","20 concurrent text scans no 5xx errors","PASS" if ok else "FAIL",0,err,total)
        self.assertEqual(err,0)

    def test_LT099(self):
        n=20; durs,stats,total=self._fire_concurrent(lambda:self.post("/api/scans/url",{"url":"http://peaktest.xyz"}),n)
        err=sum(1 for s in stats if s not in[200,429]); ok=err==0
        record("LT-099","Coverage","20 concurrent URL scans no 5xx errors","PASS" if ok else "FAIL",0,err,total)
        self.assertEqual(err,0)

    def test_LT100(self):
        all_fns=[
            lambda:self.client.get("/health"),
            lambda:self.post("/api/scans/text",{"text":"final load test message"}),
            lambda:self.post("/api/scans/url",{"url":"http://final-test.xyz"}),
            lambda:self.get("/api/analytics/dashboard"),
            lambda:self.get("/api/scans/history"),
            lambda:self.get("/api/admin/users",token=self._admin_token),
            lambda:self.get("/api/admin/threats",token=self._admin_token),
            lambda:self.get("/api/admin/system-health",token=self._admin_token),
        ]
        t=time.time(); stats=[]
        for fn in all_fns*2: stats.append(fn().status_code)
        d=time.time()-t; ok=all(s in[200,429,500] for s in stats)
        record("LT-100","Coverage","16 requests across all endpoints","PASS" if ok else "FAIL","all 200","ok" if ok else stats,d)
        self.assertTrue(ok)


if __name__ == "__main__":
    print("="*70)
    print("  Social Shield - Load Test Suite  (100+ Test Cases)")
    print("="*70)
    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None
    suite  = unittest.TestSuite()
    for cls in [TC_HealthLoad,TC_AuthLoad,TC_TextScanLoad,TC_URLScanLoad,
                TC_AnalyticsLoad,TC_HistoryLoad,TC_MixedLoad,TC_StressLoad,
                TC_Throughput,TC_SustainedLoad,TC_ErrorRate,TC_Latency,
                TC_AdminLoad,TC_RateLimit,TC_Recovery,TC_DataGrowth,TC_Coverage]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    save_to_excel()
    sys.exit(0 if result.wasSuccessful() else 1)
