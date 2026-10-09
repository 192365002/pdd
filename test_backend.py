import os
import unittest
import json
import tempfile
import numpy as np
import cv2

# Set env vars for testing
os.environ['FLASK_ENV'] = 'testing'
os.environ['JWT_SECRET'] = 'test-secret-key-that-is-at-least-32-bytes-long!'
os.environ['MONGO_URI'] = '' # Force mock database fallback

from app import app
from models import get_db, is_mock

class SocialShieldBackendTests(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        
        # Clear database records
        db = get_db()
        db['users'].data = {}
        db['scans'].data = {}
        db['threats'].data = {}
        db['notifications'].data = {}

    def test_health_check(self):
        response = self.app.get('/health')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'active')
        self.assertTrue(is_mock())

    def test_realtime_stats(self):
        response = self.app.get('/api/stats/realtime')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('trust_score', data)
        self.assertIn('total_scans', data)
        self.assertIn('ai_accuracy', data)

    def test_auth_flow(self):
        # 1. Register User
        reg_payload = {
            'email': 'test@socialshield.ai',
            'password': 'Password123!',
            'name': 'Test User',
            'role': 'user'
        }
        reg_res = self.app.post('/api/auth/register', 
                                 data=json.dumps(reg_payload),
                                 content_type='application/json')
        self.assertEqual(reg_res.status_code, 201)
        reg_data = json.loads(reg_res.data)
        self.assertIn('user_id', reg_data)
        
        db = get_db()
        self.assertEqual(db['users'].count_documents({'email': 'test@socialshield.ai'}), 1)
        db['users'].update_one({'email': 'test@socialshield.ai'}, {'$set': {'is_verified': True}})
        
        # 2. Login User
        login_payload = {
            'email': 'test@socialshield.ai',
            'password': 'Password123!'
        }
        login_res = self.app.post('/api/auth/login',
                                  data=json.dumps(login_payload),
                                  content_type='application/json')
        self.assertEqual(login_res.status_code, 200)
        login_data = json.loads(login_res.data)
        self.assertIn('token', login_data)
        token = login_data['token']

        # 3. Access Protected Route
        headers = {'Authorization': f'Bearer {token}'}
        me_res = self.app.get('/api/auth/me', headers=headers)
        self.assertEqual(me_res.status_code, 200)
        me_data = json.loads(me_res.data)
        self.assertEqual(me_data['user']['email'], 'test@socialshield.ai')

    def test_scanners(self):
        db = get_db()
        db['users'].insert_one({
            '_id': '123',
            'email': 'scanner_test@socialshield.ai',
            'password': 'hashed_password',
            'name': 'Scanner Test',
            'role': 'user',
            'is_verified': True
        })
        
        import auth
        token = auth.generate_token('123', 'user', 'Scanner Test', 'scanner_test@socialshield.ai')
        headers = {'Authorization': f'Bearer {token}'}
        
        # 1. Test Text Scam Scan
        text_payload = {'text': 'URGENT: Win a free million dollars now! Click here to redeem: http://free-scam-reward.xyz'}
        text_res = self.app.post('/api/scans/text',
                                 data=json.dumps(text_payload),
                                 content_type='application/json',
                                 headers=headers)
        self.assertEqual(text_res.status_code, 200)
        text_data = json.loads(text_res.data)
        self.assertIn('score', text_data)
        self.assertIn('risk_level', text_data)
        self.assertGreaterEqual(text_data['score'], 50)
        
        # 2. Test URL Phishing Scan
        url_payload = {'url': 'http://secure-login-paypal.xyz/auth'}
        url_res = self.app.post('/api/scans/url',
                                data=json.dumps(url_payload),
                                content_type='application/json',
                                headers=headers)
        self.assertEqual(url_res.status_code, 200)
        url_data = json.loads(url_res.data)
        self.assertIn('score', url_data)
        self.assertGreaterEqual(url_data['score'], 50)

        # 3. Test Audio Scan
        audio_payload = {'audio_base64': 'UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='}
        audio_res = self.app.post('/api/scans/audio',
                                  data=json.dumps(audio_payload),
                                  content_type='application/json',
                                  headers=headers)
        self.assertEqual(audio_res.status_code, 200)
        audio_data = json.loads(audio_res.data)
        self.assertIn('score', audio_data)
        self.assertIn('classification', audio_data)

        # 4. Test Profile Scan
        profile_payload = {
            'username': 'free_crypto_bot99281',
            'followers': 12,
            'following': 1850,
            'bio': 'DM for crypto giveaway and guaranteed 500% returns on telegram!'
        }
        prof_res = self.app.post('/api/scans/profile',
                                 data=json.dumps(profile_payload),
                                 content_type='application/json',
                                 headers=headers)
        self.assertEqual(prof_res.status_code, 200)
        prof_data = json.loads(prof_res.data)
        self.assertIn('score', prof_data)
        self.assertGreaterEqual(prof_data['score'], 60)

        # 5. Test History
        history_res = self.app.get('/api/scans/history', headers=headers)
        self.assertEqual(history_res.status_code, 200)
        history_data = json.loads(history_res.data)
        self.assertGreaterEqual(len(history_data['scans']), 4)

if __name__ == '__main__':
    unittest.main()
