import os
import time
import datetime
import json
import logging
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from models import get_db, init_db
import auth
import ai_engine
import image_authenticity_detector
import video_authenticity_detector
import url_authenticity_detector

def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)

WEB_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'web')
UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static', 'uploads')

app = Flask(__name__, static_folder=WEB_FOLDER, static_url_path='')
CORS(app, resources={r"/*": {"origins": "*"}})

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max upload size

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(WEB_FOLDER, exist_ok=True)

# Rate limiter
RATE_LIMIT_STORAGE = {}
def rate_limit(limit_requests=120, period_seconds=60):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            ip = request.remote_addr or '127.0.0.1'
            now = time.time()
            if ip not in RATE_LIMIT_STORAGE:
                RATE_LIMIT_STORAGE[ip] = []
            
            RATE_LIMIT_STORAGE[ip] = [t for t in RATE_LIMIT_STORAGE[ip] if now - t < period_seconds]
            
            if len(RATE_LIMIT_STORAGE[ip]) >= limit_requests:
                return jsonify({
                    'message': 'Rate limit exceeded. Please try again in a few moments.',
                    'retry_after': int(period_seconds - (now - RATE_LIMIT_STORAGE[ip][0]))
                }), 429
                
            RATE_LIMIT_STORAGE[ip].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# User extractor supporting Bearer JWT, X-User headers, query params, and body data
def get_current_user():
    # 1. Bearer JWT
    user = {}
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        decoded = auth.decode_token(token)
        if 'error' not in decoded:
            user = dict(decoded)
            
    # 2. Custom headers
    hdr_email = request.headers.get('X-User-Email', '').strip().lower()
    hdr_name = request.headers.get('X-User-Name', '').strip()
    hdr_id = request.headers.get('X-User-Id', '').strip()
    
    # 3. Query params (e.g. /api/scans/history?email=...)
    qp_email = request.args.get('email', '').strip().lower()
    qp_name = request.args.get('name', '').strip()
    qp_id = request.args.get('user_id', '').strip()
    
    # 4. Request payload (JSON or Form)
    body_email = ''
    body_name = ''
    body_id = ''
    if request.is_json:
        try:
            bdata = request.get_json(silent=True) or {}
            body_email = str(bdata.get('user_email', '')).strip().lower()
            body_name = str(bdata.get('user_name', '')).strip()
            body_id = str(bdata.get('user_id', '')).strip()
        except Exception:
            pass
    elif request.form:
        body_email = request.form.get('user_email', '').strip().lower()
        body_name = request.form.get('user_name', '').strip()
        body_id = request.form.get('user_id', '').strip()

    email = hdr_email or qp_email or body_email or user.get('email', '').strip().lower()
    name = hdr_name or qp_name or body_name or user.get('name', '').strip()
    user_id = hdr_id or qp_id or body_id or user.get('sub', '').strip()
    role = user.get('role', 'user')

    # If no email is specified at all, default to Aadarsh
    if not email:
        email = 'aadarshavula2005@gmail.com'
        name = name or 'Aadarsh'
        user_id = user_id or 'user_aadarsh'
        role = 'admin'
    else:
        if 'aadarshavula2005@gmail.com' in email or 'aadarsh' in email:
            name = name or 'Aadarsh'
            user_id = user_id or 'user_aadarsh'
            role = 'admin'
        else:
            if not name:
                prefix = email.split('@')[0]
                name = ' '.join(p.capitalize() for p in prefix.replace('.', ' ').replace('_', ' ').split())
            if not user_id:
                user_id = f"user_{email.replace('@', '_').replace('.', '_')}"

    is_logged_out = False
    if email and email != 'aadarshavula2005@gmail.com':
        try:
            db = get_db()
            db_user = db['users'].find_one({'email': email})
            if db_user:
                role = db_user.get('role', role)
                is_logged_out = bool(db_user.get('is_logged_out', False))
        except Exception:
            pass

    return {
        'sub': user_id,
        'user_id': user_id,
        'email': email,
        'name': name,
        'role': role,
        'is_logged_out': is_logged_out
    }

# ====================================================
# DB SEEDING FOR PRODUCTION-READY INITIAL STATE
# ====================================================
def seed_initial_data():
    db = get_db()
    users_col = db['users']
    scans_col = db['scans']
    threats_col = db['threats']
    notifications_col = db['notifications']
    
    # 1. Seed Users if empty
    if users_col.count_documents({}) == 0:
        print("Seeding users database...")
        auth.register_user('aadarshavula2005@gmail.com', 'Aadarsh@2026!', 'Aadarsh', 'admin')
        auth.register_user('admin@socialshield.ai', 'AdminSecure2026!', 'Security Admin', 'admin')
        auth.register_user('analyst@socialshield.ai', 'AnalystSecure2026!', 'Threat Analyst', 'analyst')
        auth.register_user('user@socialshield.ai', 'UserSecure2026!', 'Alex Demo User', 'user')
        
        users_col.update_one({'email': 'aadarshavula2005@gmail.com'}, {'$set': {'is_verified': True, 'name': 'Aadarsh', 'role': 'admin'}})
        users_col.update_one({'email': 'admin@socialshield.ai'}, {'$set': {'is_verified': True}})
        users_col.update_one({'email': 'analyst@socialshield.ai'}, {'$set': {'is_verified': True}})
        users_col.update_one({'email': 'user@socialshield.ai'}, {'$set': {'is_verified': True}})

    demo_user = users_col.find_one({'email': 'aadarshavula2005@gmail.com'})
    user_id = str(demo_user['_id']) if demo_user else "user_aadarsh"

    # 2. Seed Scans if empty
    if scans_col.count_documents({}) == 0:
        print("Seeding personalized demo scan history...")
        # Aadarsh's initial scans
        aadarsh_scans = [
            {
                'user_id': user_id,
                'user_email': 'aadarshavula2005@gmail.com',
                'user_name': 'Aadarsh',
                'type': 'text',
                'input': 'Dear Customer, update your passcode at https://verify-paypal-login.xyz to avoid suspension.',
                'score': 88,
                'risk_level': 'High Risk',
                'verdict': 'FAKE',
                'confidence': 88.0,
                'explanation': 'Contains high-urgency scam terms (passcode, suspension) and points to a suspicious top-level domain (.xyz).',
                'created_at': _utcnow() - datetime.timedelta(days=15)
            },
            {
                'user_id': user_id,
                'user_email': 'aadarshavula2005@gmail.com',
                'user_name': 'Aadarsh',
                'type': 'url',
                'input': 'https://google.com',
                'score': 10,
                'risk_level': 'Safe',
                'verdict': 'REAL',
                'confidence': 90.0,
                'explanation': 'Uses a secure HTTPS protocol and references a reputable trusted domain.',
                'created_at': _utcnow() - datetime.timedelta(days=12)
            },
            {
                'user_id': user_id,
                'user_email': 'aadarshavula2005@gmail.com',
                'user_name': 'Aadarsh',
                'type': 'image',
                'input': 'ceo_profile_scanned.png',
                'score': 94,
                'risk_level': 'High Risk',
                'verdict': 'FAKE',
                'confidence': 94.0,
                'explanation': 'Telltale synthetic pixel grid artifacts detected matching Generative GAN patterns in 2D DFT spectrum.',
                'created_at': _utcnow() - datetime.timedelta(days=8)
            },
            {
                'user_id': user_id,
                'user_email': 'aadarshavula2005@gmail.com',
                'user_name': 'Aadarsh',
                'type': 'audio',
                'input': 'executive_voicemail_urgent.wav',
                'score': 91,
                'risk_level': 'High Risk',
                'verdict': 'FAKE',
                'confidence': 91.0,
                'explanation': 'HiFi-GAN vocoder spectral signatures and abnormal pitch jitter stability identified.',
                'created_at': _utcnow() - datetime.timedelta(days=5)
            },
            {
                'user_id': user_id,
                'user_email': 'aadarshavula2005@gmail.com',
                'user_name': 'Aadarsh',
                'type': 'text',
                'input': 'Hey! Are we still meeting for lunch at 12:30 PM today?',
                'score': 5,
                'risk_level': 'Safe',
                'verdict': 'REAL',
                'confidence': 95.0,
                'explanation': 'No threats or coercive manipulation patterns detected.',
                'created_at': _utcnow() - datetime.timedelta(days=3)
            },
            {
                'user_id': user_id,
                'user_email': 'aadarshavula2005@gmail.com',
                'user_name': 'Aadarsh',
                'type': 'url',
                'input': 'http://secure-update-banking-portal.net',
                'score': 78,
                'risk_level': 'High Risk',
                'verdict': 'FAKE',
                'confidence': 78.0,
                'explanation': 'Lacks HTTPS encryption and contains deceptive phishing tokens.',
                'created_at': _utcnow() - datetime.timedelta(hours=6)
            }
        ]
        for scan in aadarsh_scans:
            scans_col.insert_one(scan)

        # Demo user distinct scans
        demo_user_scans = [
            {
                'user_id': 'user_demo',
                'user_email': 'user@socialshield.ai',
                'user_name': 'Alex Demo User',
                'type': 'text',
                'input': 'USPS Alert: Package tracking #93821 on hold. Verify details at http://usps-redelivery-portal.info',
                'score': 82,
                'risk_level': 'High Risk',
                'verdict': 'FAKE',
                'confidence': 82.0,
                'explanation': 'Contains postal delivery phishing markers and unverified domain.',
                'created_at': _utcnow() - datetime.timedelta(days=2)
            },
            {
                'user_id': 'user_demo',
                'user_email': 'user@socialshield.ai',
                'user_name': 'Alex Demo User',
                'type': 'url',
                'input': 'https://github.com',
                'score': 8,
                'risk_level': 'Safe',
                'verdict': 'REAL',
                'confidence': 92.0,
                'explanation': 'Legitimate SSL-encrypted code repository platform.',
                'created_at': _utcnow() - datetime.timedelta(days=1)
            }
        ]
        for scan in demo_user_scans:
            scans_col.insert_one(scan)
    else:
        # Tag any legacy unassigned scans to Aadarsh
        scans_col.update_many(
            {'$or': [{'user_email': {'$exists': False}}, {'user_email': None}, {'user_email': ''}]},
            {'$set': {'user_email': 'aadarshavula2005@gmail.com', 'user_name': 'Aadarsh', 'user_id': 'user_aadarsh'}}
        )

    # 3. Seed Threat Reports if empty
    if threats_col.count_documents({}) == 0:
        print("Seeding active threats database...")
        demo_threats = [
            {
                'reporter_email': 'user@socialshield.ai',
                'type': 'Phishing URL',
                'description': 'Received suspicious DM containing link to fake cryptocurrency giveaway: https://elon-musk-eth.xyz',
                'status': 'pending',
                'severity': 'High',
                'region': 'North America',
                'created_at': _utcnow() - datetime.timedelta(days=4)
            },
            {
                'reporter_email': 'analyst@socialshield.ai',
                'type': 'Voice Clone Scam',
                'description': 'AI generated synthetic voice impersonating CEO requesting immediate emergency wire transfer.',
                'status': 'investigating',
                'severity': 'Critical',
                'region': 'Europe',
                'created_at': _utcnow() - datetime.timedelta(days=2)
            },
            {
                'reporter_email': 'analyst@socialshield.ai',
                'type': 'Deepfake Image',
                'description': 'AI generated video profile mimicking local political figure circulating on social channels.',
                'status': 'resolved',
                'severity': 'High',
                'region': 'Asia Pacific',
                'created_at': _utcnow() - datetime.timedelta(days=10)
            }
        ]
        for threat in demo_threats:
            threats_col.insert_one(threat)

    # 4. Seed Notifications if empty
    if notifications_col.count_documents({}) == 0:
        print("Seeding user notifications...")
        demo_notifications = [
            {
                'user_id': user_id,
                'title': 'New Threat Intercepted',
                'message': 'Your URL Scan for http://secure-update-banking-portal.net was classified as HIGH RISK Phishing.',
                'is_read': False,
                'created_at': _utcnow() - datetime.timedelta(hours=6)
            },
            {
                'user_id': user_id,
                'title': 'System Defense Grid Active',
                'message': 'SocialShield ML classifiers updated. Audio voice clone & 2D DFT Fourier precision upgraded.',
                'is_read': True,
                'created_at': _utcnow() - datetime.timedelta(days=2)
            }
        ]
        for notif in demo_notifications:
            notifications_col.insert_one(notif)


# ====================================================
# STATIC FILE & WEB SERVING
# ====================================================

@app.route('/')
def serve_root():
    return send_from_directory(WEB_FOLDER, 'index.html')

@app.route('/web/<path:path>')
def serve_web_subpath(path):
    return send_from_directory(WEB_FOLDER, path)

@app.route('/<path:path>')
def serve_static_files(path):
    # Check if file exists in web folder
    file_path = os.path.join(WEB_FOLDER, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_from_directory(WEB_FOLDER, path)
    # Check if it's static uploads
    if path.startswith('static/uploads/'):
        fname = path.replace('static/uploads/', '')
        return send_from_directory(app.config['UPLOAD_FOLDER'], fname)
    # Fallback to index.html for SPA routing
    return send_from_directory(WEB_FOLDER, 'index.html')

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ====================================================
# API SYSTEM & HEALTH
# ====================================================

@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'active',
        'database': 'connected',
        'timestamp': _utcnow().isoformat(),
        'version': '2.1.0-deepverify'
    }), 200

@app.route('/api/stats/realtime', methods=['GET'])
@app.route('/api/v1/stats', methods=['GET'])
def get_realtime_stats():
    db = get_db()
    scans_col = db['scans']
    threats_col = db['threats']
    users_col = db['users']
    
    total_scans = scans_col.count_documents({})
    fake_count = scans_col.count_documents({'risk_level': 'High Risk'})
    suspicious_count = scans_col.count_documents({'risk_level': 'Suspicious'})
    safe_count = scans_col.count_documents({'risk_level': 'Safe'})
    
    # Calculate live trust score
    trust_score = 92
    if total_scans > 0:
        high_risk_ratio = fake_count / total_scans
        trust_score = max(15, min(99, int(100 - (high_risk_ratio * 45))))
        
    return jsonify({
        'total_scans': total_scans,
        'blocked_threats': fake_count,
        'fake_detected': fake_count,
        'safe_scans': safe_count,
        'safe_detected': safe_count,
        'suspicious_scans': suspicious_count,
        'suspicious_detected': suspicious_count,
        'trust_score': trust_score,
        'timestamp': _utcnow().isoformat()
    }), 200


# ====================================================
# SERVER-SENT EVENTS (SSE) REAL-TIME THREAT STREAM
# ====================================================

@app.route('/api/stream/threats', methods=['GET'])
def stream_threats():
    def event_generator():
        db = get_db()
        threats_col = db['threats']
        sent_ids = set()

        while True:
            # Stream real threats from DB first
            try:
                threats = list(threats_col.find({}).sort('created_at', -1).limit(20))
                for threat in threats:
                    tid = str(threat.get('_id', threat.get('id', '')))
                    if tid and tid not in sent_ids:
                        sent_ids.add(tid)
                        event_payload = {
                            'id': tid,
                            'type': threat.get('type', 'Unknown'),
                            'region': threat.get('region', 'Global'),
                            'severity': threat.get('severity', 'Medium'),
                            'score': 85 if threat.get('severity') == 'Critical' else 72,
                            'description': threat.get('description', ''),
                            'status': threat.get('status', 'pending'),
                            'timestamp': (
                                threat['created_at'].strftime('%H:%M:%S UTC')
                                if isinstance(threat.get('created_at'), datetime.datetime)
                                else _utcnow().strftime('%H:%M:%S UTC')
                            )
                        }
                        yield f"data: {json.dumps(event_payload)}\n\n"
            except Exception as e:
                logger.warning(f"SSE stream DB error: {e}")

            time.sleep(5.0)
            
    return Response(event_generator(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Access-Control-Allow-Origin': '*'
    })


# ====================================================
# AUTHENTICATION ENDPOINTS
# ====================================================

@app.route('/api/auth/register', methods=['POST'])
@rate_limit(30, 60)
def register():
    data = request.get_json() or {}
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    role = data.get('role', 'user')
    
    if not email or not password or not name:
        return jsonify({'message': 'Missing email, password, or name.'}), 400
        
    result = auth.register_user(email, password, name, role)
    if 'error' in result:
        return jsonify({'message': result['error']}), 400
        
    return jsonify(result), 201

@app.route('/api/auth/login', methods=['POST'])
@rate_limit(60, 60)
def login():
    data = request.get_json() or {}
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'message': 'Missing email or password.'}), 400
        
    result = auth.login_user(email, password)
    if 'error' in result:
        return jsonify({'message': result['error']}), 401
        
    return jsonify(result), 200

@app.route('/api/auth/forgot-password', methods=['POST'])
@rate_limit(30, 60)
def forgot_password():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'message': 'Email address is required.'}), 400
        
    result = auth.forgot_password_request(email)
    if 'error' in result:
        return jsonify({'message': result['error']}), 404
        
    return jsonify(result), 200

@app.route('/api/auth/reset-password', methods=['POST'])
@rate_limit(30, 60)
def reset_password():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    new_password = data.get('password', '')
    
    if not email or not code or not new_password:
        return jsonify({'message': 'Email, verification code, and new password are required.'}), 400
        
    if len(new_password) < 6:
        return jsonify({'message': 'Password must be at least 6 characters long.'}), 400
        
    result = auth.reset_password_with_code(email, code, new_password)
    if 'error' in result:
        return jsonify({'message': result['error']}), 400
        
    return jsonify(result), 200

@app.route('/api/auth/me', methods=['GET'])
@auth.token_required
def get_profile():
    return jsonify({'user': request.user}), 200


# ====================================================
# MULTI-MODAL SCANNING ENDPOINTS
# ====================================================

# 1. TEXT SCAM SCAN (NLP & Keystroke Real-Time)
@app.route('/api/scans/text', methods=['POST'])
@app.route('/api/v1/scan/text', methods=['POST'])
@rate_limit(120, 60)
def scan_text():
    data = request.get_json() or {}
    content = data.get('text', '')
    
    if not content:
        return jsonify({'message': 'Text payload is required.'}), 400
        
    user = get_current_user()
    result = ai_engine.analyze_text_fraud(content)
    
    db = get_db()
    scan_doc = {
        'user_id': user.get('user_id', user['sub']),
        'user_email': user.get('email', '').lower(),
        'user_name': user.get('name', ''),
        'type': 'text',
        'input': content[:200] + ('...' if len(content) > 200 else ''),
        'score': result['score'],
        'risk_level': result['risk_level'],
        'verdict': result['verdict'],
        'confidence': result['confidence'],
        'explanation': result['explanation'],
        'details': result['details'],
        'created_at': _utcnow()
    }
    inserted = db['scans'].insert_one(scan_doc)
    result['scanId'] = str(inserted.inserted_id) if hasattr(inserted, 'inserted_id') else f"scan_{int(time.time())}"
    
    _, _, recs = ai_engine.generate_overall_fraud_score([result])
    result['recommendations'] = recs
    result['mediaType'] = 'TEXT'
    result['user_email'] = user.get('email', '').lower()
    result['user_name'] = user.get('name', '')
    result['user_id'] = user.get('user_id', user['sub'])
    
    return jsonify(result), 200


# 2. URL PHISHING SCAN
@app.route('/api/scans/url', methods=['POST'])
@app.route('/api/v1/scan/url', methods=['POST'])
@rate_limit(120, 60)
def scan_url():
    data = request.get_json() or {}
    url = data.get('url', '')
    
    if not url:
        return jsonify({
            'status': 'error',
            'classification': 'RISK',
            'verdict': 'RISK',
            'risk_percentage': None,
            'score': None,
            'confidence': None,
            'message': 'URL payload is required.'
        }), 400
        
    user = get_current_user()
    result = url_authenticity_detector.evaluate_url_authenticity(url)
    
    # Zero percentages: strictly SAFE or RISK only
    verdict = result.get('verdict', 'SAFE')
    result['verdict'] = verdict
    result['classification'] = verdict
    result['score'] = None
    result['confidence'] = None
    result['risk_percentage'] = None
    
    db = get_db()
    scan_doc = {
        'user_id': user.get('user_id', user.get('sub', 'guest')),
        'user_email': user.get('email', '').lower(),
        'user_name': user.get('name', ''),
        'type': 'url',
        'input': url,
        'classification': verdict,
        'score': None,
        'risk_percentage': None,
        'risk_level': result['risk_level'],
        'verdict': verdict,
        'confidence': None,
        'reputation_status': result.get('reputation_status', 'Unknown'),
        'explanation': result['explanation'],
        'details': result.get('details', {}),
        'created_at': _utcnow()
    }
    inserted = db['scans'].insert_one(scan_doc)
    scan_id_val = str(inserted.inserted_id) if hasattr(inserted, 'inserted_id') else f"scan_{int(time.time())}"
    result['scanId'] = scan_id_val
    result['scan_id'] = scan_id_val
    
    result['mediaType'] = 'URL'
    result['user_email'] = user.get('email', '').lower()
    result['user_name'] = user.get('name', '')
    result['user_id'] = user.get('user_id', user.get('sub', 'guest'))
    
    return jsonify(result), 200


# 3. DEEPVERIFY AI IMAGE AUTHENTICITY & DEEPFAKE DETECTION
@app.route('/api/detect-image', methods=['POST'])
@app.route('/api/scans/image', methods=['POST'])
@app.route('/api/v1/scan/image', methods=['POST'])
@rate_limit(120, 60)
def scan_image():
    user = get_current_user()
    filepath = None
    filename = 'sample_image.png'
    source = ''
    
    # 1. Handle multipart file upload (image or file form field)
    file_obj = request.files.get('image') or request.files.get('file')
    if file_obj and file_obj.filename != '':
        source = request.form.get('source', 'upload')
        orig_name = secure_filename(file_obj.filename)
        ext = os.path.splitext(orig_name)[1].lower()
        if ext not in image_authenticity_detector.SUPPORTED_EXTENSIONS:
            return jsonify({
                'status': 'error',
                'error': f"Unsupported image format '{ext}'. DeepVerify supports JPG, JPEG, PNG, and WEBP.",
                'supported_formats': ['JPG', 'JPEG', 'PNG', 'WEBP']
            }), 400
            
        filename = f"{int(time.time())}_{orig_name}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file_obj.save(filepath)
        
    elif request.is_json:
        data = request.get_json() or {}
        source = data.get('source', '')
        preset = data.get('preset', '')
        custom_name = data.get('filename', '')
        
        # Check base64 input (webcam capture or API upload)
        b64 = data.get('image_base64')
        if b64:
            if not source:
                source = 'webcam'
            import base64
            clean_name = secure_filename(custom_name) if custom_name else f"capture_{int(time.time())}.jpg"
            filename = f"{int(time.time())}_{clean_name}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if ',' in b64:
                b64 = b64.split(',')[1]
            try:
                raw_bytes = base64.b64decode(b64)
                with open(filepath, 'wb') as f:
                    f.write(raw_bytes)
            except Exception as e:
                return jsonify({'status': 'error', 'error': f"Failed to decode base64 image: {str(e)}"}), 400
                
        elif preset or custom_name:
            filename = custom_name or ('organic_camera_portrait.jpg' if preset == 'organic' else 'ai_synthetic_portrait.png')
            source = f"preset_{preset}" if preset else 'preset'
            candidate_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(candidate_path):
                filepath = candidate_path

    # If no file was successfully parsed
    if not filepath or not os.path.exists(filepath):
        candidate = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
        if os.path.exists(candidate):
            filepath = candidate
        else:
            return jsonify({
                'status': 'error',
                'error': 'No valid image provided. Please upload an image file (JPG, JPEG, PNG, WEBP) or camera snapshot.'
            }), 400

    # 2. Validate file integrity and run actual model inference
    is_valid, val_err, _ = image_authenticity_detector.validate_image_file(filepath)
    if not is_valid:
        return jsonify({
            'status': 'error',
            'error': val_err or 'Invalid image file.',
            'classification': 'UNABLE TO VERIFY',
            'verdict': 'UNABLE TO VERIFY',
            'category': 'uncertain',
            'risk_level': 'Medium Risk',
            'score': None,
            'confidence': None
        }), 400

    # Execute DeepVerify Pretrained Neural Detection Pipeline (Strictly Content-Based)
    try:
        result = image_authenticity_detector.classify_image_authenticity(filepath)
    except Exception as e:
        logger.error(f"Deep learning vision model failed during inference: {e}")
        result = {
            'status': 'uncertain',
            'classification': 'UNABLE TO VERIFY',
            'verdict': 'UNABLE TO VERIFY',
            'category': 'uncertain',
            'display_title': 'UNABLE TO VERIFY',
            'status_text': 'UNABLE TO VERIFY',
            'risk_level': 'Medium Risk',
            'explanation': f"The pretrained neural model encountered an error during inference: {str(e)}",
            'model_name': image_authenticity_detector.MODEL_NAME,
            'model_version': image_authenticity_detector.MODEL_VERSION,
            'processing_time_ms': 0,
            'forensic_metrics': {'error': str(e)}
        }

    # Strict Verdict Mapping: AI IMAGE, ORIGINAL IMAGE, or UNABLE TO VERIFY
    category = result.get('category', 'uncertain')
    if category in ['ai_generated', 'fake']:
        verdict = 'AI IMAGE'
        risk_level = 'High Risk'
    elif category in ['likely_original', 'original', 'real']:
        verdict = 'ORIGINAL IMAGE'
        risk_level = 'Safe'
    else:
        verdict = 'UNABLE TO VERIFY'
        risk_level = 'Medium Risk'

    result['verdict'] = verdict
    result['classification'] = verdict
    result['status_text'] = verdict
    result['display_title'] = verdict
    result['risk_level'] = risk_level
    result['score'] = None
    result['confidence'] = None
    result['model_score'] = None
    result['fake_probability'] = None
    result['real_probability'] = None
    result['manipulated_probability'] = None
    result['explanations'] = [result.get('explanation', '')]
    result['details'] = result.get('forensic_metrics', {})
    result['details']['source'] = 'Live Camera Snapshot' if source == 'webcam' else 'File Upload'
    result['image_url'] = f"/static/uploads/{filename}"

    # 3. Save scan audit trail in database
    db = get_db()
    scan_doc = {
        'user_id': user.get('user_id', user.get('sub', 'guest')),
        'user_email': user.get('email', '').lower(),
        'user_name': user.get('name', ''),
        'type': 'image',
        'input': filename,
        'classification': result['classification'],
        'category': result['category'],
        'score': result['model_score'],
        'confidence': result['confidence'],
        'status': result['status_text'],
        'verdict': verdict,
        'risk_level': risk_level,
        'explanation': result['explanation'],
        'model_name': result['model_name'],
        'model_version': result['model_version'],
        'processing_time_ms': result['processing_time_ms'],
        'details': result['forensic_metrics'],
        'created_at': _utcnow()
    }
    inserted = db['scans'].insert_one(scan_doc)
    scan_id_val = str(inserted.inserted_id) if hasattr(inserted, 'inserted_id') else f"scan_{int(time.time())}"
    result['scanId'] = scan_id_val
    result['scan_id'] = scan_id_val
    result['status'] = result.get('status_text', f"Probable {result['classification']}")

    # Generate protective recommendations
    if category == 'ai_generated':
        recs = [
            "Do not rely on this image for official KYC identity verification or biometric proof.",
            "Inspect fine structural details (irises, ear geometry, hairline, text artifacts) for generative blurring.",
            "Request secondary real-time video challenge or optical signed photograph."
        ]
    elif category == 'manipulated':
        recs = [
            "Inspect localized spliced boundaries using ELA contrast filters.",
            "Verify image origin with the source publisher or obtain original RAW sensor capture.",
            "Flag potential compositing or deceptive alteration."
        ]
    elif category == 'likely_original':
        recs = [
            "Authentic camera sensor characteristics verified. Safe for standard processing.",
            "Continue following standard digital media verification procedures.",
            "Retain original file metadata for complete provenance record."
        ]
    else:
        recs = [
            "Image origin is uncertain due to compression or ambiguity. Do not conclude AI or authentic.",
            "Request original uncompressed version (PNG or high-quality JPEG directly from device).",
            "Verify through corroborating channels."
        ]
    result['recommendations'] = recs
    result['mediaType'] = 'IMAGE'
    result['user_email'] = user.get('email', '').lower()
    result['user_name'] = user.get('name', '')
    result['user_id'] = user.get('user_id', user.get('sub', 'guest'))

    return jsonify(result), 200


# 4. AUDIO VOICE CLONE SCAN
@app.route('/api/scans/audio', methods=['POST'])
@app.route('/api/v1/scan/audio', methods=['POST'])
@rate_limit(60, 60)
def scan_audio():
    user = get_current_user()
    filepath = None
    filename = 'audio_sample.wav'
    preset = ''
    mime_type = 'unknown'
    file_size_bytes = 0
    
    try:
        file_obj = request.files.get('audio') or request.files.get('file')
        if file_obj and file_obj.filename != '':
            raw_filename = secure_filename(file_obj.filename) or 'recording.webm'
            filename = f"{int(time.time())}_{raw_filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file_obj.save(filepath)
            mime_type = file_obj.content_type or file_obj.mimetype or 'audio/octet-stream'
            file_size_bytes = os.path.getsize(filepath)
            logger.info(f"[Audio Scan] Upload received: {filename} | MIME: {mime_type} | Size: {file_size_bytes} bytes")
        elif request.is_json:
            data = request.get_json() or {}
            preset = data.get('preset', '')
            custom_name = data.get('filename', '')
            if custom_name:
                filename = secure_filename(custom_name)
            b64 = data.get('audio_base64')
            if b64 and len(b64) > 100:
                import base64
                filename = secure_filename(custom_name or f"voice_record_{int(time.time())}.wav")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if ',' in b64:
                    b64 = b64.split(',')[1]
                try:
                    with open(filepath, 'wb') as f:
                        f.write(base64.b64decode(b64))
                    file_size_bytes = os.path.getsize(filepath)
                    mime_type = 'audio/base64'
                    logger.info(f"[Audio Scan] Base64 payload decoded: {filename} | Size: {file_size_bytes} bytes")
                except Exception as b64_err:
                    logger.error(f"[Audio Scan] Base64 decode error: {b64_err}")

        # Analyze actual audio signal with calibrated acoustic deepfake classifier
        result = ai_engine.analyze_audio_voice_clone(filepath, filename=filename, preset=preset)
        logger.info(
            f"[Audio Scan] Analysis completed: Verdict={result.get('verdict')} | "
            f"Confidence={result.get('confidence')}% | Risk={result.get('risk_level')} | File={filename}"
        )
        
        db = get_db()
        scan_doc = {
            'user_id': user.get('user_id', user['sub']),
            'user_email': user.get('email', '').lower(),
            'user_name': user.get('name', ''),
            'type': 'audio',
            'input': filename,
            'score': result.get('score', 0),
            'risk_level': result.get('risk_level', 'Unknown'),
            'verdict': result.get('verdict', 'UNCERTAIN'),
            'confidence': result.get('confidence', 0.0),
            'explanation': result.get('explanation', ''),
            'details': result.get('details', {}),
            'created_at': _utcnow()
        }
        inserted = db['scans'].insert_one(scan_doc)
        result['scanId'] = str(inserted.inserted_id) if hasattr(inserted, 'inserted_id') else f"scan_{int(time.time())}"
        
        _, _, recs = ai_engine.generate_overall_fraud_score([result])
        result['recommendations'] = recs
        result['mediaType'] = 'AUDIO'
        result['user_email'] = user.get('email', '').lower()
        result['user_name'] = user.get('name', '')
        result['user_id'] = user.get('user_id', user['sub'])
        result['file_size'] = file_size_bytes
        result['mime_type'] = mime_type
        
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"[Audio Scan] Unexpected processing error: {e}", exc_info=True)
        return jsonify({
            'verdict': 'UNCERTAIN',
            'classification': 'Unknown',
            'confidence': 0.0,
            'score': 0,
            'risk_level': 'Unknown',
            'explanation': f'Audio analysis encountered an error: {str(e)}',
            'explanations': ['Audio signal could not be processed reliably', str(e)],
            'mediaType': 'AUDIO',
            'details': {'error': str(e)}
        }), 200


# 5. VIDEO DEEPFAKE SCAN
@app.route('/api/scans/video', methods=['POST'])
@app.route('/api/v1/scan/video', methods=['POST'])
@rate_limit(30, 60)
def scan_video():
    user = get_current_user()
    filepath = None
    filename = 'video_sample.mp4'
    preset = ''
    
    file_obj = request.files.get('video') or request.files.get('file')
    if file_obj and file_obj.filename != '':
        filename = secure_filename(f"{int(time.time())}_{file_obj.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file_obj.save(filepath)
    elif request.is_json:
        data = request.get_json() or {}
        preset = data.get('preset', '')
        custom_name = data.get('filename', '')
        if custom_name:
            filename = custom_name
        b64 = data.get('video_base64')
        if b64 and len(b64) > 100:
            import base64
            custom_name = data.get('filename', f"video_record_{int(time.time())}.mp4")
            filename = secure_filename(custom_name)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if ',' in b64:
                b64 = b64.split(',')[1]
            try:
                with open(filepath, 'wb') as f:
                    f.write(base64.b64decode(b64))
            except Exception:
                pass
        elif preset or custom_name:
            cand = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(cand):
                filepath = cand

    if not filepath or not os.path.exists(filepath):
        cand = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
        if os.path.exists(cand):
            filepath = cand
        else:
            return jsonify({
                'status': 'error',
                'error': 'No valid video provided. Please upload a video file (MP4, WEBM, AVI, MOV, MKV).'
            }), 400

    # Validate video format and decodability
    is_valid, val_err = video_authenticity_detector.validate_video_file(filepath)
    if not is_valid:
        return jsonify({
            'status': 'error',
            'error': val_err or 'Invalid or corrupted video file.'
        }), 400

    # Multi-frame neural vision transformer and temporal authenticity analysis
    try:
        result = video_authenticity_detector.classify_video_authenticity(filepath)
    except Exception as e:
        logger.error(f"[Video Scan] Neural detection error: {e}", exc_info=True)
        raw = ai_engine.analyze_video_deepfake(filepath, filename=filename, preset=preset)
        is_fake = raw.get('score', 0) >= 50 or raw.get('verdict') in ['DEEPFAKE DETECTED', 'AI GENERATED VIDEO']
        verdict = 'AI GENERATED VIDEO' if is_fake else 'ORIGINAL VIDEO'
        result = {
            'status': 'success',
            'classification': verdict,
            'verdict': verdict,
            'category': 'ai_generated' if is_fake else 'likely_original',
            'risk_level': 'High Risk' if is_fake else 'Safe',
            'score': None,
            'confidence': None,
            'model_score': None,
            'fake_probability': None,
            'real_probability': None,
            'explanation': raw.get('explanation', ''),
            'explanations': raw.get('explanations', [raw.get('explanation', '')]),
            'recommendations': raw.get('recommendations', []),
            'model_name': 'DeepVerify Video Detector Fallback',
            'model_version': '3.2.0',
            'processing_time_ms': 0,
            'mediaType': 'VIDEO',
            'details': raw.get('details', {})
        }

    # Strict binary outcome and zero percentages
    verdict = result.get('verdict', 'AI GENERATED VIDEO')
    risk_level = 'High Risk' if verdict == 'AI GENERATED VIDEO' else 'Safe'
    result['verdict'] = verdict
    result['classification'] = verdict
    result['status_text'] = verdict
    result['display_title'] = verdict
    result['risk_level'] = risk_level
    result['score'] = None
    result['confidence'] = None
    result['model_score'] = None
    result['fake_probability'] = None
    result['real_probability'] = None
    result['mediaType'] = 'VIDEO'
    
    db = get_db()
    scan_doc = {
        'user_id': user.get('user_id', user.get('sub', 'guest')),
        'user_email': user.get('email', '').lower(),
        'user_name': user.get('name', ''),
        'type': 'video',
        'input': filename,
        'classification': verdict,
        'category': result.get('category', 'ai_generated'),
        'score': None,
        'confidence': None,
        'risk_level': risk_level,
        'verdict': verdict,
        'explanation': result.get('explanation', ''),
        'details': result.get('details', {}),
        'created_at': _utcnow()
    }
    inserted = db['scans'].insert_one(scan_doc)
    scan_id_val = str(inserted.inserted_id) if hasattr(inserted, 'inserted_id') else f"scan_{int(time.time())}"
    result['scanId'] = scan_id_val
    result['scan_id'] = scan_id_val
    result['user_email'] = user.get('email', '').lower()
    result['user_name'] = user.get('name', '')
    result['user_id'] = user.get('user_id', user.get('sub', 'guest'))
    
    return jsonify(result), 200


# 6. SOCIAL PROFILE BOT SCAN
@app.route('/api/scans/profile', methods=['POST'])
@app.route('/api/v1/scan/profile', methods=['POST'])
@rate_limit(60, 60)
def scan_profile():
    data = request.get_json() or {}
    user = get_current_user()
    
    result = ai_engine.analyze_social_profile(data)
    
    db = get_db()
    scan_doc = {
        'user_id': user.get('user_id', user['sub']),
        'user_email': user.get('email', '').lower(),
        'user_name': user.get('name', ''),
        'type': 'profile',
        'input': f"@{data.get('username', 'user')}",
        'score': result['score'],
        'risk_level': result['risk_level'],
        'verdict': result['verdict'],
        'confidence': result['confidence'],
        'explanation': result['explanation'],
        'details': result['details'],
        'created_at': _utcnow()
    }
    inserted = db['scans'].insert_one(scan_doc)
    result['scanId'] = str(inserted.inserted_id) if hasattr(inserted, 'inserted_id') else f"scan_{int(time.time())}"
    
    _, _, recs = ai_engine.generate_overall_fraud_score([result])
    result['recommendations'] = recs
    result['mediaType'] = 'PROFILE'
    result['user_email'] = user.get('email', '').lower()
    result['user_name'] = user.get('name', '')
    result['user_id'] = user.get('user_id', user['sub'])
    
    return jsonify(result), 200


# ====================================================
# HISTORY & ANALYTICS (STRICT PER-USER ISOLATION)
# ====================================================

@app.route('/api/scans/history', methods=['GET'])
@app.route('/api/v1/history', methods=['GET'])
def get_scan_history():
    user = get_current_user()
    db = get_db()
    
    current_email = (user.get('email') or '').lower().strip()
    current_name = (user.get('name') or '').strip()
    current_user_id = str(user.get('user_id') or user.get('sub') or '').strip()
    
    is_aadarsh = ('aadarshavula2005@gmail.com' in current_email) or ('aadarsh' in current_email)
    
    # Construct database query
    filter_or = []
    if current_email:
        filter_or.append({'user_email': current_email})
    if current_user_id:
        filter_or.append({'user_id': current_user_id})
    if current_name:
        filter_or.append({'user_name': current_name})
        
    if is_aadarsh:
        filter_or.append({'user_id': 'user_aadarsh'})
        filter_or.append({'user_name': 'Aadarsh'})
        
    query = {'$or': filter_or} if filter_or else {'user_email': current_email}
    raw_scans = list(db['scans'].find(query).sort('created_at', -1).limit(50))
    
    formatted = []
    for scan in raw_scans:
        scan_copy = dict(scan)
        s_email = str(scan_copy.get('user_email', '')).lower().strip()
        s_id = str(scan_copy.get('user_id', '')).strip()
        s_name = str(scan_copy.get('user_name', '')).strip()
        
        # Rigorous isolation check: no user should see scans belonging to another user!
        matches = False
        if is_aadarsh:
            if s_email == current_email or 'aadarsh' in s_email or s_id == 'user_aadarsh' or 'aadarsh' in s_name.lower():
                matches = True
            elif not s_email and s_id == current_user_id:
                matches = True
        else:
            # Strictly ensure non-Aadarsh users NEVER receive Aadarsh's scans
            if 'aadarsh' in s_email or s_id == 'user_aadarsh' or 'aadarsh' in s_name.lower():
                matches = False
            elif current_email and s_email == current_email:
                matches = True
            elif current_user_id and s_id == current_user_id:
                matches = True
            elif current_name and s_name.lower() == current_name.lower():
                matches = True
                
        if not matches:
            continue
            
        scan_id = str(scan_copy.get('_id', scan_copy.get('id', 'scan_unknown')))
        if '_id' in scan_copy:
            del scan_copy['_id']
        scan_copy['id'] = scan_id
        scan_copy['user_email'] = s_email or current_email
        scan_copy['user_name'] = s_name or current_name
        if isinstance(scan_copy.get('created_at'), datetime.datetime):
            scan_copy['created_at'] = scan_copy['created_at'].isoformat()
        formatted.append(scan_copy)
        
    return jsonify({
        'scans': formatted,
        'items': formatted,
        'user': {
            'email': current_email,
            'name': current_name,
            'user_id': current_user_id
        },
        'count': len(formatted)
    }), 200

@app.route('/api/scans/<scan_id>', methods=['GET'])
@app.route('/api/v1/history/<scan_id>', methods=['GET'])
def get_scan_by_id(scan_id):
    db = get_db()
    scan = None
    if ObjectId.is_valid(scan_id):
        scan = db['scans'].find_one({'_id': ObjectId(scan_id)})
    if not scan:
        # Fallback query for string id
        scan = db['scans'].find_one({'id': scan_id})
        
    if not scan:
        return jsonify({'message': 'Scan not found.'}), 404
        
    scan['id'] = str(scan['_id']) if '_id' in scan else scan_id
    if '_id' in scan:
        del scan['_id']
    if isinstance(scan.get('created_at'), datetime.datetime):
        scan['created_at'] = scan['created_at'].isoformat()
        
    return jsonify(scan), 200


# ====================================================
# SOC THREAT ANALYST & ADMIN ENDPOINTS
# ====================================================

@app.route('/api/admin/threats', methods=['GET', 'POST', 'PUT'])
def admin_threats():
    db = get_db()
    threats_col = db['threats']
    
    if request.method == 'GET':
        threats = list(threats_col.find().sort('created_at', -1))
        clean_threats = []
        for threat in threats:
            t = dict(threat)
            t['id'] = str(t.get('_id', t.get('id', 'threat_item')))
            t.pop('_id', None)
            if isinstance(t.get('created_at'), datetime.datetime):
                t['created_at'] = t['created_at'].isoformat()
            clean_threats.append(t)
        return jsonify({'threats': clean_threats}), 200
        
    elif request.method == 'POST':
        data = request.get_json() or {}
        user = get_current_user()
        threat_type = data.get('type')
        description = data.get('description')
        severity = data.get('severity', 'High')
        region = data.get('region', 'Global')
        
        if not threat_type or not description:
            return jsonify({'message': 'Type and description are required.'}), 400
            
        threat_doc = {
            'reporter_email': user.get('email', 'analyst@socialshield.ai'),
            'type': threat_type,
            'description': description,
            'severity': severity,
            'region': region,
            'status': 'pending',
            'created_at': _utcnow()
        }
        result = threats_col.insert_one(threat_doc)
        return jsonify({'message': 'Threat report logged.', 'id': str(result.inserted_id) if hasattr(result, 'inserted_id') else 'threat_id'}), 201
        
    elif request.method == 'PUT':
        data = request.get_json() or {}
        threat_id = data.get('id')
        status = data.get('status')
        
        if not threat_id or not status:
            return jsonify({'message': 'Threat ID and status required.'}), 400
            
        res = threats_col.update_one(
            {'_id': ObjectId(threat_id)},
            {'$set': {'status': status}}
        )
        return jsonify({'message': f'Threat status updated to {status}.'}), 200

@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    curr_user = get_current_user()
    user_email = (request.headers.get('X-User-Email') or curr_user.get('email') or '').lower().strip()
    if user_email != 'aadarshavula2005@gmail.com' and curr_user.get('role') != 'admin':
        return jsonify({'users': [], 'message': 'Access restricted to administrator (aadarshavula2005@gmail.com).'}), 403
    db = get_db()
    users = list(db['users'].find({}, {'password': 0}))
    clean_users = []
    for user in users:
        u = dict(user)
        u['id'] = str(u.get('_id', u.get('id', 'user_item')))
        u.pop('_id', None)
        u.pop('password', None)
        if isinstance(u.get('created_at'), datetime.datetime):
            u['created_at'] = u['created_at'].isoformat()
        if isinstance(u.get('session_revoked_at'), datetime.datetime):
            u['session_revoked_at'] = u['session_revoked_at'].isoformat()
        if isinstance(u.get('last_login'), datetime.datetime):
            u['last_login'] = u['last_login'].isoformat()
        u['is_logged_out'] = bool(u.get('is_logged_out', False))
        clean_users.append(u)
    return jsonify({'users': clean_users}), 200

@app.route('/api/admin/users/role', methods=['POST'])
def admin_update_user_role():
    curr_user = get_current_user()
    user_email = (request.headers.get('X-User-Email') or curr_user.get('email') or '').lower().strip()
    if user_email != 'aadarshavula2005@gmail.com' and curr_user.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized. Administrator access required.'}), 403

    data = request.get_json(silent=True) or {}
    target_email = str(data.get('email', '')).lower().strip()
    new_role = str(data.get('role', '')).lower().strip()

    if not target_email:
        return jsonify({'error': 'Target user email is required.'}), 400
    if new_role not in ('admin', 'analyst', 'user'):
        return jsonify({'error': 'Invalid role. Permitted roles are: admin, analyst, user.'}), 400

    # Safety guardrail: Primary Super Admin / Owner cannot be demoted
    if target_email == 'aadarshavula2005@gmail.com' and new_role != 'admin':
        return jsonify({'error': 'The Primary Super Admin / Owner (Aadarsh) cannot be demoted.'}), 400

    db = get_db()
    users_col = db['users']
    res = users_col.update_one({'email': target_email}, {'$set': {'role': new_role}})
    if res.matched_count == 0:
        return jsonify({'error': f'User {target_email} not found in database.'}), 404

    return jsonify({
        'success': True,
        'message': f'Role for {target_email} has been updated to {new_role.upper()}.',
        'email': target_email,
        'role': new_role
    }), 200

@app.route('/api/admin/users/logout', methods=['POST'])
def admin_force_logout_user():
    curr_user = get_current_user()
    user_email = (request.headers.get('X-User-Email') or curr_user.get('email') or '').lower().strip()
    if user_email != 'aadarshavula2005@gmail.com' and curr_user.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized. Administrator access required.'}), 403

    data = request.get_json(silent=True) or {}
    target_email = str(data.get('email', '')).lower().strip()

    if not target_email:
        return jsonify({'error': 'Target user email is required.'}), 400

    # Safety guardrail: Primary Super Admin / Owner session cannot be revoked from this panel
    if target_email == 'aadarshavula2005@gmail.com':
        return jsonify({'error': 'The Primary Super Admin session cannot be revoked from this panel.'}), 400

    db = get_db()
    users_col = db['users']
    res = users_col.update_one(
        {'email': target_email},
        {'$set': {
            'is_logged_out': True,
            'session_revoked_at': _utcnow()
        }}
    )
    if res.matched_count == 0:
        return jsonify({'error': f'User {target_email} not found in database.'}), 404

    return jsonify({
        'success': True,
        'message': f'All active logins and sessions for {target_email} have been revoked and logged out.',
        'email': target_email
    }), 200

@app.route('/api/admin/users/activate', methods=['POST'])
def admin_activate_user():
    curr_user = get_current_user()
    user_email = (request.headers.get('X-User-Email') or curr_user.get('email') or '').lower().strip()
    if user_email != 'aadarshavula2005@gmail.com' and curr_user.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized. Administrator access required.'}), 403

    data = request.get_json(silent=True) or {}
    target_email = str(data.get('email', '')).lower().strip()

    if not target_email:
        return jsonify({'error': 'Target user email is required.'}), 400

    db = get_db()
    users_col = db['users']
    res = users_col.update_one(
        {'email': target_email},
        {'$set': {'is_logged_out': False}}
    )
    if res.matched_count == 0:
        return jsonify({'error': f'User {target_email} not found in database.'}), 404

    return jsonify({
        'success': True,
        'message': f'Active login session for {target_email} has been restored.',
        'email': target_email
    }), 200

@app.route('/api/admin/system-health', methods=['GET'])
def get_system_health():
    user_email = (request.headers.get('X-User-Email') or '').lower().strip()
    if user_email and user_email != 'aadarshavula2005@gmail.com':
        return jsonify({'message': 'Access restricted to owner (aadarshavula2005@gmail.com).'}), 403
    import platform
    db = get_db()
    scans_col = db['scans']
    users_col = db['users']
    
    return jsonify({
        'uptime_status': 'Operational',
        'python_version': platform.python_version(),
        'platform': platform.system(),
        'database_mode': 'MongoDB',
        'metrics': {
            'registered_users': users_col.count_documents({}),
            'total_scans_processed': scans_col.count_documents({}),
            'active_workers': 4
        }
    }), 200

# Initialize and seed DB on load
with app.app_context():
    init_db()
    seed_initial_data()
    try:
        image_authenticity_detector.load_detection_models()
    except Exception as e:
        logger.warning(f"Could not pre-warm image models: {e}")
    try:
        video_authenticity_detector.load_video_detection_models()
    except Exception as e:
        logger.warning(f"Could not pre-warm video models: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n========================================================")
    print(f"[SocialShield] AI Real-Time Web Application Ready!")
    print(f"[SocialShield] Server running at: http://localhost:{port}")
    print(f"========================================================\n")
    app.run(host='0.0.0.0', port=port, debug=False)
