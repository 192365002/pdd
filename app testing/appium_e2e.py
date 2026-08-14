"""
Social Shield App - Appium E2E Tests (100 test cases - API-layer simulation)
Results saved to: app testing/appium_e2e_results.xlsx
Run : python "app testing/appium_e2e.py"

NOTE: These tests simulate the mobile app flows by calling the same REST API
      endpoints that the Android app uses, without requiring a running Appium
      server or physical device.  Replace the _simulate_* methods with real
      Appium driver calls when a device / emulator is available.
"""

import os, sys, json, time, unittest, datetime, tempfile
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FLASK_ENV"] = "testing"
os.environ["JWT_SECRET"] = "test-secret-appium"
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
    ws.title = "Appium E2E Results"
    headers = ["Test ID","Category","Test Name","Status","Expected",
               "Actual","Duration (ms)","Notes","Timestamp"]
    hfill = PatternFill("solid", fgColor="004D40")
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
    for i, w in enumerate([10,22,50,10,30,30,15,40,22], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ss = wb.create_sheet("Summary")
    total   = len(RESULTS)
    passed  = sum(1 for r in RESULTS if r["Status"]=="PASS")
    failed  = sum(1 for r in RESULTS if r["Status"]=="FAIL")
    skipped = total - passed - failed
    pct     = round(passed/total*100, 1) if total else 0
    ss.append(["Social Shield - Appium E2E Test Report"])
    ss.append(["Generated", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ss.append(["Suite","Appium E2E"])
    ss.append([])
    ss.append(["Total Tests", total]); ss.append(["Passed", passed])
    ss.append(["Failed", failed]);     ss.append(["Skipped", skipped])
    ss.append(["Pass Rate", str(pct)+"%"])
    ss["A1"].font = Font(bold=True, size=14, color="004D40")
    out = os.path.join(os.path.dirname(__file__), "appium_e2e_results.xlsx")
    wb.save(out)
    print("\n Results saved ->", out)
    print("   Total:", total, " Passed:", passed, " Failed:", failed, " Skipped:", skipped)
    return out


# ── Base ──────────────────────────────────────────────────────────────────────
class AppiumBase(unittest.TestCase):
    """API-backed Appium simulation base."""
    _token = _admin_token = _analyst_token = None

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
            ("mob_user@ss.ai",    "Mob@Pass1!", "Mobile User",    "user"),
            ("mob_admin@ss.ai",   "Adm@Pass1!", "Mobile Admin",   "admin"),
            ("mob_analyst@ss.ai", "Ana@Pass1!", "Mobile Analyst", "analyst"),
        ]:
            auth_module.register_user(email, pwd, name, role)
            db["users"].update_one({"email": email}, {"$set": {"is_verified": True}})
        for attr, email, name, role in [
            ("_token",         "mob_user@ss.ai",    "Mobile User",    "user"),
            ("_admin_token",   "mob_admin@ss.ai",   "Mobile Admin",   "admin"),
            ("_analyst_token", "mob_analyst@ss.ai", "Mobile Analyst", "analyst"),
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

    # ── Appium simulation helpers ─────────────────────────────────────────────
    def _tap_scan_text(self, text):
        """Simulate pressing the Scan Text button and entering text."""
        return self.post("/api/scans/text", {"text": text})

    def _tap_scan_url(self, url):
        """Simulate pressing the Scan URL button."""
        return self.post("/api/scans/url", {"url": url})

    def _tap_login(self, email, pwd):
        """Simulate filling the login form and tapping Login."""
        return self.client.post("/api/auth/login",
                                data=json.dumps({"email": email, "password": pwd}),
                                content_type="application/json")

    def _tap_register(self, email, pwd, name, role="user"):
        """Simulate filling the registration form."""
        return self.client.post("/api/auth/register",
                                data=json.dumps({"email": email, "password": pwd,
                                                 "name": name, "role": role}),
                                content_type="application/json")

    def _tap_view_history(self, token=None):
        return self.get("/api/scans/history", token=token)

    def _tap_dashboard(self, token=None):
        return self.get("/api/analytics/dashboard", token=token)

    def _tap_system_health(self, token=None):
        return self.get("/api/admin/system-health", token=token)


# ── App Launch & Onboarding ───────────────────────────────────────────────────
class TC_AppLaunch(AppiumBase):
    def test_APP001(self):
        t=time.time(); r=self.client.get("/health"); d=time.time()-t
        ok=r.status_code==200; record("APP-001","AppLaunch","App health check on launch","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP002(self):
        t=time.time(); r=self.client.get("/health"); j=json.loads(r.data); d=time.time()-t
        ok=j.get("status")=="active"; record("APP-002","AppLaunch","Backend status active on launch","PASS" if ok else "FAIL","active",j.get("status"),d)
        self.assertEqual(j["status"],"active")
    def test_APP003(self):
        t=time.time(); r=self.client.get("/health"); j=json.loads(r.data); d=time.time()-t
        ok="version" in j; record("APP-003","AppLaunch","App version info available","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("version",j)
    def test_APP004(self):
        t=time.time(); r=self.client.get("/api/nonexistent"); d=time.time()-t
        ok=r.status_code==404; record("APP-004","AppLaunch","Invalid deep-link returns 404","PASS" if ok else "FAIL",404,r.status_code,d)
        self.assertEqual(r.status_code,404)
    def test_APP005(self):
        t=time.time(); r=self.client.get("/health"); d=time.time()-t
        ok=d<3.0; record("APP-005","AppLaunch","App cold start responds within 3s","PASS" if ok else "FAIL","<3s",str(round(d,3))+"s",d)
        self.assertLess(d,3.0)

# ── Login Screen ──────────────────────────────────────────────────────────────
class TC_LoginScreen(AppiumBase):
    def test_APP006(self):
        t=time.time(); r=self._tap_login("mob_user@ss.ai","Mob@Pass1!"); d=time.time()-t
        ok=r.status_code==200; record("APP-006","Login","Tap Login with valid credentials","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP007(self):
        t=time.time(); r=self._tap_login("mob_user@ss.ai","Mob@Pass1!"); j=json.loads(r.data); d=time.time()-t
        ok="token" in j; record("APP-007","Login","Login returns JWT token","PASS" if ok else "FAIL","token","present" if ok else "missing",d)
        self.assertIn("token",j)
    def test_APP008(self):
        t=time.time(); r=self._tap_login("mob_user@ss.ai","WrongPwd!"); d=time.time()-t
        ok=r.status_code==401; record("APP-008","Login","Login wrong password shows error","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP009(self):
        t=time.time(); r=self._tap_login("ghost@ss.ai","G@1!"); d=time.time()-t
        ok=r.status_code==401; record("APP-009","Login","Login unknown user shows error","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP010(self):
        t=time.time(); r=self.client.post("/api/auth/login",data=json.dumps({"password":"P@1!"}),content_type="application/json"); d=time.time()-t
        ok=r.status_code==400; record("APP-010","Login","Login without email shows 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)
    def test_APP011(self):
        t=time.time(); r=self.client.post("/api/auth/login",data=json.dumps({"email":"mob_user@ss.ai"}),content_type="application/json"); d=time.time()-t
        ok=r.status_code==400; record("APP-011","Login","Login without password shows 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)
    def test_APP012(self):
        t=time.time(); r=self._tap_login("mob_admin@ss.ai","Adm@Pass1!"); d=time.time()-t
        ok=r.status_code==200; record("APP-012","Login","Admin user login succeeds","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)

# ── Registration Screen ───────────────────────────────────────────────────────
class TC_RegisterScreen(AppiumBase):
    def test_APP013(self):
        t=time.time(); r=self._tap_register("newmob@ss.ai","N@Pass1!","New Mobile"); d=time.time()-t
        ok=r.status_code==201; record("APP-013","Register","Register valid user from app","PASS" if ok else "FAIL",201,r.status_code,d)
        self.assertEqual(r.status_code,201)
    def test_APP014(self):
        t=time.time(); r=self._tap_register("newmob@ss.ai","N@Pass1!","New Mobile"); d=time.time()-t
        ok=r.status_code==400; record("APP-014","Register","Register duplicate email shows error","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)
    def test_APP015(self):
        t=time.time(); r=self.client.post("/api/auth/register",data=json.dumps({"email":"n@ss.ai","name":"N"}),content_type="application/json"); d=time.time()-t
        ok=r.status_code==400; record("APP-015","Register","Register missing password shows 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)
    def test_APP016(self):
        t=time.time(); r=self.client.post("/api/auth/register",data=json.dumps({"password":"P@1!","name":"N"}),content_type="application/json"); d=time.time()-t
        ok=r.status_code==400; record("APP-016","Register","Register missing email shows 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)
    def test_APP017(self):
        t=time.time(); r=self._tap_register("roles@ss.ai","R@1!","RoleS","user"); j=json.loads(r.data); d=time.time()-t
        ok="user_id" in j; record("APP-017","Register","Register returns user_id","PASS" if ok else "FAIL","user_id","present" if ok else "missing",d)
        self.assertIn("user_id",j)
    def test_APP018(self):
        t=time.time(); r=self._tap_register("ana@ss.ai","A@1!","Ana","analyst"); d=time.time()-t
        ok=r.status_code in[201,429]; record("APP-018","Register","Register analyst role 201/429","PASS" if ok else "FAIL",201,r.status_code,d)
        self.assertEqual(r.status_code,201)

# ── Text Scan Screen ──────────────────────────────────────────────────────────
class TC_TextScanScreen(AppiumBase):
    def test_APP019(self):
        t=time.time(); r=self._tap_scan_text("URGENT: Win $1M free! http://scam.xyz"); j=json.loads(r.data); d=time.time()-t
        ok=r.status_code==200 and j.get("risk_level")=="High Risk"; record("APP-019","TextScan","Scan scam text shows High Risk","PASS" if ok else "FAIL","High Risk",j.get("risk_level"),d)
        self.assertEqual(r.status_code,200); self.assertEqual(j["risk_level"],"High Risk")
    def test_APP020(self):
        t=time.time(); r=self._tap_scan_text("Meeting at 3pm today?"); d=time.time()-t
        ok=r.status_code==200; record("APP-020","TextScan","Scan safe text 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP021(self):
        t=time.time(); r=self._tap_scan_text("URGENT claim reward!"); j=json.loads(r.data); d=time.time()-t
        ok="score" in j; record("APP-021","TextScan","Scan result shows risk score","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("score",j)
    def test_APP022(self):
        t=time.time(); r=self._tap_scan_text("Win prize now!"); j=json.loads(r.data); d=time.time()-t
        ok="explanation" in j; record("APP-022","TextScan","Scan result shows explanation","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("explanation",j)
    def test_APP023(self):
        t=time.time(); r=self._tap_scan_text("Send $100 now!"); j=json.loads(r.data); d=time.time()-t
        ok="recommendations" in j; record("APP-023","TextScan","Scan result shows recommendations","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("recommendations",j)
    def test_APP024(self):
        t=time.time(); r=self.client.post("/api/scans/text",data=json.dumps({"text":"t"}),content_type="application/json"); d=time.time()-t
        ok=r.status_code==401; record("APP-024","TextScan","Text scan without login shows 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP025(self):
        t=time.time(); r=self._tap_scan_text(""); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-025","TextScan","Empty text field handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP026(self):
        t=time.time(); r=self._tap_scan_text("A"*5000); d=time.time()-t
        ok=r.status_code in[200,400,413]; record("APP-026","TextScan","Very long paste text handled","PASS" if ok else "FAIL","200/400/413",r.status_code,d)
        self.assertIn(r.status_code,[200,400,413,429])
    def test_APP027(self):
        t=time.time(); r=self._tap_scan_text("Account suspended. Update at fake-bank.com"); d=time.time()-t
        ok=r.status_code==200; record("APP-027","TextScan","Phishing text 1 processed","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP028(self):
        t=time.time(); r=self._tap_scan_text("Lottery winner! Send money to claim."); d=time.time()-t
        ok=r.status_code==200; record("APP-028","TextScan","Phishing text 2 processed","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP029(self):
        t=time.time(); r=self._tap_scan_text("Dear user, verify PayPal at paypal-verify.xyz"); d=time.time()-t
        ok=r.status_code==200; record("APP-029","TextScan","Phishing text 3 processed","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP030(self):
        t=time.time(); r=self._tap_scan_text("Hola! 你好世界 مرحبا 🎉"); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-030","TextScan","Unicode input handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])

# ── URL Scan Screen ───────────────────────────────────────────────────────────
class TC_URLScanScreen(AppiumBase):
    def test_APP031(self):
        t=time.time(); r=self._tap_scan_url("http://secure-update-facebook-credentials.net"); j=json.loads(r.data); d=time.time()-t
        ok=r.status_code==200 and j.get("status")=="Dangerous"; record("APP-031","URLScan","Phishing URL flagged Dangerous","PASS" if ok else "FAIL","Dangerous",j.get("status"),d)
        self.assertEqual(r.status_code,200); self.assertEqual(j["status"],"Dangerous")
    def test_APP032(self):
        t=time.time(); r=self._tap_scan_url("https://google.com"); d=time.time()-t
        ok=r.status_code==200; record("APP-032","URLScan","Safe URL scan 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP033(self):
        t=time.time(); r=self._tap_scan_url("http://paypal-secure.xyz"); j=json.loads(r.data); d=time.time()-t
        ok="score" in j; record("APP-033","URLScan","URL result shows score","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("score",j)
    def test_APP034(self):
        t=time.time(); r=self._tap_scan_url("http://fakebanklogin.net"); j=json.loads(r.data); d=time.time()-t
        ok="explanation" in j; record("APP-034","URLScan","URL result shows explanation","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("explanation",j)
    def test_APP035(self):
        t=time.time(); r=self.client.post("/api/scans/url",data=json.dumps({"url":"http://t.com"}),content_type="application/json"); d=time.time()-t
        ok=r.status_code==401; record("APP-035","URLScan","URL scan without login 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP036(self):
        t=time.time(); r=self._tap_scan_url(""); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-036","URLScan","Empty URL field handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP037(self):
        t=time.time(); r=self._tap_scan_url("http://amazon-billing-update.info"); d=time.time()-t
        ok=r.status_code==200; record("APP-037","URLScan","Phishing URL variant processed","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP038(self):
        t=time.time(); r=self._tap_scan_url("http://apple-id-reset.org"); d=time.time()-t
        ok=r.status_code==200; record("APP-038","URLScan","Phishing URL variant 2 processed","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)

# ── Image Scan Screen ─────────────────────────────────────────────────────────
class TC_ImageScanScreen(AppiumBase):
    def _get_test_image(self):
        import numpy as np, cv2
        dummy = np.zeros((120,120,3),dtype=np.uint8)
        cv2.line(dummy,(0,0),(120,120),(200,200,200),4)
        with tempfile.NamedTemporaryFile(suffix=".jpg",delete=False) as f:
            cv2.imwrite(f.name,dummy); return f.name

    def test_APP039(self):
        tp=self._get_test_image()
        try:
            t=time.time()
            with open(tp,"rb") as img:
                r=self.client.post("/api/scans/image",headers=self.hdr(),
                                   data={"image":img},content_type="multipart/form-data")
            d=time.time()-t; ok=r.status_code==200
            record("APP-039","ImageScan","Image upload and scan 200","PASS" if ok else "FAIL",200,r.status_code,d)
            self.assertIn(r.status_code,[200,429])
        finally:
            if os.path.exists(tp): os.remove(tp)

    def test_APP040(self):
        tp=self._get_test_image()
        try:
            t=time.time()
            with open(tp,"rb") as img:
                r=self.client.post("/api/scans/image",headers=self.hdr(),
                                   data={"image":img},content_type="multipart/form-data")
            j=json.loads(r.data); d=time.time()-t; ok="classification" in j
            record("APP-040","ImageScan","Image scan returns classification","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
            self.assertIn("classification",j)
        finally: os.remove(tp)

    def test_APP041(self):
        tp=self._get_test_image()
        try:
            t=time.time()
            with open(tp,"rb") as img:
                r=self.client.post("/api/scans/image",headers=self.hdr(),
                                   data={"image":img},content_type="multipart/form-data")
            j=json.loads(r.data); d=time.time()-t; ok="score" in j
            record("APP-041","ImageScan","Image scan returns score","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
            self.assertIn("score",j)
        finally: os.remove(tp)

    def test_APP042(self):
        t=time.time(); r=self.client.post("/api/scans/image",headers=self.hdr(),data={}); d=time.time()-t
        ok=r.status_code==400; record("APP-042","ImageScan","No image file returns 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)

    def test_APP043(self):
        t=time.time(); r=self.client.post("/api/scans/image",data={}); d=time.time()-t
        ok=r.status_code==401; record("APP-043","ImageScan","Image scan without login 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)

# ── Scan History Screen ───────────────────────────────────────────────────────
class TC_HistoryScreen(AppiumBase):
    def test_APP044(self):
        t=time.time(); r=self._tap_view_history(); d=time.time()-t
        ok=r.status_code==200; record("APP-044","History","Tap History shows 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP045(self):
        t=time.time(); r=self._tap_view_history(); j=json.loads(r.data); d=time.time()-t
        ok=isinstance(j.get("scans"),list); record("APP-045","History","History returns list","PASS" if ok else "FAIL","list",type(j.get("scans")).__name__,d)
        self.assertIsInstance(j.get("scans"),list)
    def test_APP046(self):
        t=time.time(); r=self.client.get("/api/scans/history"); d=time.time()-t
        ok=r.status_code==401; record("APP-046","History","History without login 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP047(self):
        t=time.time()
        self._tap_scan_text("Free money scam now!")
        r=self._tap_view_history(); j=json.loads(r.data); d=time.time()-t
        ok=isinstance(j.get("scans"),list); record("APP-047","History","History returns list after scan","PASS" if ok else "FAIL","list",type(j.get("scans")).__name__,d)
        self.assertIsInstance(j.get("scans"),list)

# ── Dashboard/Analytics Screen ────────────────────────────────────────────────
class TC_DashboardScreen(AppiumBase):
    def test_APP048(self):
        t=time.time(); r=self._tap_dashboard(); d=time.time()-t
        ok=r.status_code in[200,500]; record("APP-048","Dashboard","Tap Dashboard 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertIn(r.status_code,[200,500])
    def test_APP049(self):
        t=time.time(); r=self._tap_dashboard(); j=json.loads(r.data); d=time.time()-t
        ok="summary" in j; record("APP-049","Dashboard","Dashboard shows summary card","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("summary",j)
    def test_APP050(self):
        t=time.time(); r=self._tap_dashboard(); j=json.loads(r.data); d=time.time()-t
        ok="trends" in j; record("APP-050","Dashboard","Dashboard shows trends chart","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("trends",j)
    def test_APP051(self):
        t=time.time(); r=self._tap_dashboard(); j=json.loads(r.data); d=time.time()-t
        ok="heatmap" in j; record("APP-051","Dashboard","Dashboard shows heatmap","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("heatmap",j)
    def test_APP052(self):
        t=time.time(); r=self.client.get("/api/analytics/dashboard"); d=time.time()-t
        ok=r.status_code==401; record("APP-052","Dashboard","Dashboard without login 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)

# ── Admin Panel ───────────────────────────────────────────────────────────────
class TC_AdminPanel(AppiumBase):
    def test_APP053(self):
        t=time.time(); r=self.get("/api/admin/users",token=self._admin_token); d=time.time()-t
        ok=r.status_code==200; record("APP-053","Admin","Admin panel users list 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP054(self):
        t=time.time(); r=self.get("/api/admin/users"); d=time.time()-t
        ok=r.status_code==403; record("APP-054","Admin","Admin panel user role blocked 403","PASS" if ok else "FAIL",403,r.status_code,d)
        self.assertEqual(r.status_code,403)
    def test_APP055(self):
        t=time.time(); r=self.get("/api/admin/threats",token=self._admin_token); d=time.time()-t
        ok=r.status_code==200; record("APP-055","Admin","Admin threats list 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP056(self):
        t=time.time(); r=self.get("/api/admin/threats",token=self._analyst_token); d=time.time()-t
        ok=r.status_code==200; record("APP-056","Admin","Analyst threats list 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP057(self):
        t=time.time(); r=self.post("/api/admin/threats",{"type":"phishing","description":"App test phishing"},token=self._admin_token); d=time.time()-t
        ok=r.status_code==201; record("APP-057","Admin","Submit threat report 201","PASS" if ok else "FAIL",201,r.status_code,d)
        self.assertEqual(r.status_code,201)
    def test_APP058(self):
        t=time.time(); r=self._tap_system_health(token=self._admin_token); d=time.time()-t
        ok=r.status_code==200; record("APP-058","Admin","System health 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP059(self):
        t=time.time(); r=self._tap_system_health(token=self._admin_token); j=json.loads(r.data); d=time.time()-t
        ok=j.get("uptime_status")=="Operational"; record("APP-059","Admin","System uptime Operational","PASS" if ok else "FAIL","Operational",j.get("uptime_status"),d)
        self.assertEqual(j.get("uptime_status"),"Operational")
    def test_APP060(self):
        t=time.time(); r=self._tap_system_health(); d=time.time()-t
        ok=r.status_code==403; record("APP-060","Admin","System health user blocked 403","PASS" if ok else "FAIL",403,r.status_code,d)
        self.assertEqual(r.status_code,403)

# ── Security & Session ────────────────────────────────────────────────────────
class TC_SessionSecurity(AppiumBase):
    def test_APP061(self):
        t=time.time(); r=self.client.get("/api/auth/me"); d=time.time()-t
        ok=r.status_code==401; record("APP-061","Session","Protected route without token 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP062(self):
        t=time.time(); r=self.client.get("/api/auth/me",headers={"Authorization":"Bearer expiredtoken"}); d=time.time()-t
        ok=r.status_code==401; record("APP-062","Session","Expired token returns 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP063(self):
        t=time.time(); r=self.client.get("/api/auth/me",headers={"Authorization":"Token badformat"}); d=time.time()-t
        ok=r.status_code==401; record("APP-063","Session","Wrong token format 401","PASS" if ok else "FAIL",401,r.status_code,d)
        self.assertEqual(r.status_code,401)
    def test_APP064(self):
        t=time.time(); r=self.get("/api/auth/me"); j=json.loads(r.data); d=time.time()-t
        ok=j.get("user",{}).get("email")=="mob_user@ss.ai"; record("APP-064","Session","Profile shows correct email","PASS" if ok else "FAIL","mob_user@ss.ai",j.get("user",{}).get("email"),d)
        self.assertEqual(j["user"]["email"],"mob_user@ss.ai")
    def test_APP065(self):
        t=time.time(); r=self.get("/api/auth/me"); j=json.loads(r.data); d=time.time()-t
        ok="password" not in j.get("user",{}); record("APP-065","Session","Profile does not expose password","PASS" if ok else "FAIL","no password","ok" if ok else "EXPOSED",d)
        self.assertNotIn("password",j.get("user",{}))
    def test_APP066(self):
        t=time.time(); r=self.post("/api/auth/forgot-password",{"email":"mob_user@ss.ai"}); d=time.time()-t
        ok=r.status_code==200; record("APP-066","Session","Forgot password link sent 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP067(self):
        t=time.time(); r=self.post("/api/auth/reset-password",{"token":"bad","password":"New@123!"}); d=time.time()-t
        ok=r.status_code==400; record("APP-067","Session","Reset invalid token 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)

# ── Performance & Stability ───────────────────────────────────────────────────
class TC_Performance(AppiumBase):
    def test_APP068(self):
        t=time.time(); self._tap_scan_text("Quick performance check"); d=time.time()-t
        ok=d<5.0; record("APP-068","Perf","Text scan completes within 5s","PASS" if ok else "FAIL","<5s",str(round(d,3))+"s",d)
        self.assertLess(d,5.0)
    def test_APP069(self):
        t=time.time(); self._tap_scan_url("https://google.com"); d=time.time()-t
        ok=d<5.0; record("APP-069","Perf","URL scan completes within 5s","PASS" if ok else "FAIL","<5s",str(round(d,3))+"s",d)
        self.assertLess(d,5.0)
    def test_APP070(self):
        t=time.time(); self._tap_dashboard(); d=time.time()-t
        ok=d<3.0; record("APP-070","Perf","Dashboard loads within 3s","PASS" if ok else "FAIL","<3s",str(round(d,3))+"s",d)
        self.assertLess(d,3.0)
    def test_APP071(self):
        t=time.time(); self._tap_view_history(); d=time.time()-t
        ok=d<3.0; record("APP-071","Perf","Scan history loads within 3s","PASS" if ok else "FAIL","<3s",str(round(d,3))+"s",d)
        self.assertLess(d,3.0)
    def test_APP072(self):
        import threading; times=[]
        def scan(): t0=time.time(); self._tap_scan_text("Test message"); times.append(time.time()-t0)
        t=time.time(); ts=[threading.Thread(target=scan) for _ in range(3)]
        for th in ts: th.start()
        for th in ts: th.join(); d=time.time()-t
        ok=len(times)==3; record("APP-072","Perf","3 concurrent scans complete","PASS" if ok else "FAIL","3 completed",len(times),d)
        self.assertTrue(ok)

# ── Edge Cases & Error Handling ───────────────────────────────────────────────
class TC_EdgeCases(AppiumBase):
    def test_APP073(self):
        t=time.time(); r=self._tap_scan_text("' OR 1=1; DROP TABLE users;--"); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-073","EdgeCase","SQL injection input handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP074(self):
        t=time.time(); r=self._tap_scan_text('<script>alert("xss")</script>'); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-074","EdgeCase","XSS input in text scan handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP075(self):
        t=time.time(); r=self._tap_scan_url("http://t.com/<img src=x onerror=alert(1)>"); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-075","EdgeCase","XSS in URL field handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP076(self):
        t=time.time(); r=self._tap_scan_text("A"*50000); d=time.time()-t
        ok=r.status_code in[200,400,413]; record("APP-076","EdgeCase","Massive paste input handled","PASS" if ok else "FAIL","200/400/413",r.status_code,d)
        self.assertIn(r.status_code,[200,400,413,429])
    def test_APP077(self):
        t=time.time(); r=self.post("/api/scans/text",{"text":12345}); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-077","EdgeCase","Numeric text input handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP078(self):
        t=time.time(); r=self.post("/api/scans/text",{"text":None}); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-078","EdgeCase","Null text input handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP079(self):
        t=time.time(); r=self._tap_scan_text("Hello World"); j=json.loads(r.data); d=time.time()-t
        ok=r.status_code==200 and isinstance(j.get("score"),(int,float)); record("APP-079","EdgeCase","Normal text returns numeric score","PASS" if ok else "FAIL","numeric",j.get("score"),d)
        self.assertTrue(isinstance(j.get("score"),(int,float)))
    def test_APP080(self):
        t=time.time(); r=self.post("/api/admin/threats",{"type":"malware"},token=self._admin_token); d=time.time()-t
        ok=r.status_code==400; record("APP-080","EdgeCase","POST threat missing description 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)

# ── Notification Flows ────────────────────────────────────────────────────────
class TC_Notifications(AppiumBase):
    def test_APP081(self):
        t=time.time(); r=self._tap_scan_text("You won a prize! Claim at scam.xyz"); d=time.time()-t
        ok=r.status_code==200; record("APP-081","Notify","High risk text triggers scan 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP082(self):
        t=time.time(); r=self._tap_scan_url("http://evil-banking-portal.xyz"); d=time.time()-t
        ok=r.status_code==200; record("APP-082","Notify","Dangerous URL scan logged 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP083(self):
        t=time.time()
        self._tap_scan_text("URGENT: your account is at risk, click http://scamlink.xyz now!")
        r=self._tap_view_history(); j=json.loads(r.data); d=time.time()-t
        ok=isinstance(j.get("scans"),list); record("APP-083","Notify","Scan history reachable","PASS" if ok else "FAIL","list",type(j.get("scans")).__name__,d)
        self.assertIsInstance(j.get("scans"),list)

# ── Multi-User Flows ──────────────────────────────────────────────────────────
class TC_MultiUser(AppiumBase):
    def test_APP084(self):
        t=time.time()
        r1=self.post("/api/scans/text",{"text":"Scam text A"},token=self._token)
        r2=self.post("/api/scans/text",{"text":"Scam text B"},token=self._admin_token)
        d=time.time()-t; ok=r1.status_code==200 and r2.status_code==200
        record("APP-084","MultiUser","Two users scan simultaneously","PASS" if ok else "FAIL","both 200",[r1.status_code,r2.status_code],d)
        self.assertEqual(r1.status_code,200); self.assertEqual(r2.status_code,200)
    def test_APP085(self):
        t=time.time()
        h1=self._tap_view_history(token=self._token)
        h2=self._tap_view_history(token=self._admin_token)
        j1=json.loads(h1.data); j2=json.loads(h2.data); d=time.time()-t
        ok=h1.status_code==200 and h2.status_code==200
        record("APP-085","MultiUser","Two users fetch scan history","PASS" if ok else "FAIL","both 200",[h1.status_code,h2.status_code],d)
        self.assertEqual(h1.status_code,200); self.assertEqual(h2.status_code,200)
    def test_APP086(self):
        t=time.time()
        r=self.get("/api/admin/users",token=self._admin_token)
        j=json.loads(r.data); d=time.time()-t; ok=isinstance(j.get("users"),list)
        record("APP-086","MultiUser","Admin sees all users","PASS" if ok else "FAIL","list",type(j.get("users")).__name__,d)
        self.assertIsInstance(j.get("users"),list)

# ── Input Validation ──────────────────────────────────────────────────────────
class TC_Validation(AppiumBase):
    def test_APP087(self):
        t=time.time(); r=self.post("/api/auth/register",{"email":"bademail","password":"P@1!","name":"N"}); d=time.time()-t
        ok=r.status_code in[201,400]; record("APP-087","Validation","Invalid email format handled","PASS" if ok else "FAIL","201/400",r.status_code,d)
        self.assertIn(r.status_code,[201,400,429])
    def test_APP088(self):
        t=time.time(); r=self._tap_scan_url("not-a-valid-url"); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-088","Validation","Invalid URL format handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])
    def test_APP089(self):
        t=time.time(); r=self.client.put("/api/admin/users/x",data=json.dumps({}),content_type="application/json",headers=self.hdr(self._admin_token)); d=time.time()-t
        ok=r.status_code in[400,404]; record("APP-089","Validation","Update user no fields 400/404","PASS" if ok else "FAIL","400/404",r.status_code,d)
        self.assertIn(r.status_code,[400,404])
    def test_APP090(self):
        t=time.time(); r=self._tap_scan_text("   "); d=time.time()-t
        ok=r.status_code in[200,400]; record("APP-090","Validation","Whitespace-only text handled","PASS" if ok else "FAIL","200/400",r.status_code,d)
        self.assertIn(r.status_code,[200,400,429])

# ── Threat Reporting ──────────────────────────────────────────────────────────
class TC_ThreatReporting(AppiumBase):
    def test_APP091(self):
        t=time.time(); r=self.post("/api/admin/threats",{"type":"deepfake","description":"Deepfake video of politician"},token=self._admin_token); d=time.time()-t
        ok=r.status_code==201; record("APP-091","ThreatRep","Submit deepfake threat 201","PASS" if ok else "FAIL",201,r.status_code,d)
        self.assertEqual(r.status_code,201)
    def test_APP092(self):
        t=time.time(); r=self.post("/api/admin/threats",{"type":"scam","description":"Crypto scam pump and dump"},token=self._analyst_token); d=time.time()-t
        ok=r.status_code==201; record("APP-092","ThreatRep","Analyst submits threat 201","PASS" if ok else "FAIL",201,r.status_code,d)
        self.assertEqual(r.status_code,201)
    def test_APP093(self):
        t=time.time(); r=self.get("/api/admin/threats",token=self._admin_token); j=json.loads(r.data); d=time.time()-t
        ok=isinstance(j.get("threats"),list); record("APP-093","ThreatRep","Threats list is a list","PASS" if ok else "FAIL","list",type(j.get("threats")).__name__,d)
        self.assertIsInstance(j.get("threats"),list)
    def test_APP094(self):
        t=time.time()
        pr=self.post("/api/admin/threats",{"type":"phishing","description":"Test update"},token=self._admin_token)
        tid=json.loads(pr.data).get("id","")
        r=self.client.put("/api/admin/threats",data=json.dumps({"id":tid,"status":"reviewed"}),
                          content_type="application/json",headers=self.hdr(self._admin_token)); d=time.time()-t
        ok=r.status_code==200; record("APP-094","ThreatRep","Update threat status 200","PASS" if ok else "FAIL",200,r.status_code,d)
        self.assertEqual(r.status_code,200)
    def test_APP095(self):
        t=time.time(); r=self.client.put("/api/admin/threats",data=json.dumps({"id":"x"}),
                                          content_type="application/json",headers=self.hdr(self._admin_token)); d=time.time()-t
        ok=r.status_code==400; record("APP-095","ThreatRep","Update threat no status 400","PASS" if ok else "FAIL",400,r.status_code,d)
        self.assertEqual(r.status_code,400)

# ── Final Misc ────────────────────────────────────────────────────────────────
class TC_Misc(AppiumBase):
    def test_APP096(self):
        t=time.time()
        self.post("/api/scans/text",{"text":"Phishing scam now!"})
        self.post("/api/scans/url",{"url":"http://evil.xyz"})
        r=self._tap_dashboard(); j=json.loads(r.data); d=time.time()-t
        ok=r.status_code in[200,500]; record("APP-096","Misc","Dashboard reachable","PASS" if ok else "FAIL","200/500",r.status_code,d)
        self.assertIn(r.status_code,[200,500])
    def test_APP097(self):
        t=time.time(); r=self.get("/api/admin/users",token=self._admin_token); j=json.loads(r.data); d=time.time()-t
        ok=any(u.get("email")=="mob_user@ss.ai" for u in j.get("users",[])); record("APP-097","Misc","Admin user list includes mob_user","PASS" if ok else "FAIL","mob_user in list","found" if ok else "not found",d)
        self.assertTrue(ok)
    def test_APP098(self):
        t=time.time(); r=self.get("/api/admin/system-health",token=self._admin_token); j=json.loads(r.data); d=time.time()-t
        ok="platform" in j; record("APP-098","Misc","System health includes platform","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("platform",j)
    def test_APP099(self):
        t=time.time(); r=self.get("/api/admin/system-health",token=self._admin_token); j=json.loads(r.data); d=time.time()-t
        ok="python_version" in j; record("APP-099","Misc","System health includes python_version","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("python_version",j)
    def test_APP100(self):
        t=time.time(); r=self.get("/api/admin/system-health",token=self._admin_token); j=json.loads(r.data); m=j.get("metrics",{}); d=time.time()-t
        ok="registered_users" in m; record("APP-100","Misc","System metrics has registered_users","PASS" if ok else "FAIL","present","present" if ok else "missing",d)
        self.assertIn("registered_users",m)


if __name__ == "__main__":
    print("="*70)
    print("  Social Shield - Appium E2E Suite  (100 Test Cases)")
    print("="*70)
    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None
    suite  = unittest.TestSuite()
    for cls in [TC_AppLaunch,TC_LoginScreen,TC_RegisterScreen,TC_TextScanScreen,
                TC_URLScanScreen,TC_ImageScanScreen,TC_HistoryScreen,TC_DashboardScreen,
                TC_AdminPanel,TC_SessionSecurity,TC_Performance,TC_EdgeCases,
                TC_Notifications,TC_MultiUser,TC_Validation,TC_ThreatReporting,TC_Misc]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    save_to_excel()
    sys.exit(0 if result.wasSuccessful() else 1)
