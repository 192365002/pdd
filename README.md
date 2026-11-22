# 🛡️ DeepVerify / SocialShield — Multi-Modal AI Fraud & Deepfake Detection

[![CI/CD Pipeline - Tests & Deployment](https://github.com/192365002/pdd/actions/workflows/deploy.yml/badge.svg)](https://github.com/192365002/pdd/actions/workflows/deploy.yml)
[![Deployment](https://img.shields.io/badge/Deployment-GitHub%20Pages-blue?logo=github)](https://192365002.github.io/pdd/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](https://python.org)
[![Testing](https://img.shields.io/badge/Tests-Pytest%20%26%20Selenium-brightgreen?logo=pytest)](https://pytest.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An enterprise-grade cyber defense and media verification platform engineered with Python Flask, PyTorch/Vision Transformers, and OpenCV to detect and neutralize synthetic media manipulation across multiple digital vectors:

- **🖼️ Image Deepfake & Synthetic Media Detection**: 2D Discrete Fourier Transform (DFT) spectral lattice analysis, Nyquist boundary anomaly detection, and Vision Transformer diffusion artifact identification.
- **🎙️ Voice Clone & Mic Acoustic Forensics**: High-resolution acoustic spectrogram analysis, synthetic spectral centroid jitter tracking, and neural vocoder (HiFi-GAN, WaveGlow, ElevenLabs) speech pattern recognition.
- **🎥 Video Deepfake Temporal Analysis**: Frame-by-frame facial landmark stability, inter-frame temporal coherence, and generative flickering detection.
- **⚡ Debounced NLP Text Scam Analysis**: Real-time linguistic token risk scoring, urgency and credential-harvesting heuristic classification.
- **🔗 Phishing URL & Domain Forensics**: Punycode homograph analysis, suspicious TLD tracking, entropy scoring, and domain age intelligence.

---

## 🌐 Live Web Deployment

The static web interface is continuously deployed to **GitHub Pages**:
👉 **[https://192365002.github.io/pdd/](https://192365002.github.io/pdd/)**

> **Note on Enabling GitHub Pages in GitHub:**
> 1. Go to repository **Settings** > **Pages**
> 2. Under **Build and deployment > Source**, select **GitHub Actions**
> 3. Pushes to `main` will automatically build, test, and deploy the updated application!

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| **Backend & APIs** | Python 3.11+, Flask, Flask-CORS, PyJWT, Bcrypt, Gunicorn |
| **AI / ML & DSP** | Scikit-learn, OpenCV (opencv-python-headless), NumPy, SciPy, PyAV, SoundFile, Joblib |
| **Database** | MongoDB Atlas (Cloud) with automatic SQLite resilient fallback |
| **Frontend** | Vanilla ES6+ Web Audio API & HTML5 Glassmorphism UI + React/Vite client |
| **Automated Testing** | Pytest 8+, Selenium WebDriver 4.20+, Headless Chrome, OpenPyXL, JUnit XML |
| **CI / CD DevOps** | GitHub Actions, Ubuntu Runner, Automated Artifact Archiving, GitHub Pages |

---

## 🚀 Local Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/192365002/pdd.git
cd pdd
```

### 2. Set Up Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the template configuration file:
```bash
cp .env.example .env
```
Update `.env` with your desired configuration (e.g., `PORT`, `JWT_SECRET`, and optional `MONGO_URI` / `SMTP` credentials). If no `MONGO_URI` is supplied, the system seamlessly defaults to the local SQLite database (`socialshield.db`).

### 5. Start the Web Server
```bash
python app.py
```
Open your browser at **[http://localhost:5000](http://localhost:5000)**.

---

## 🧪 Running Automated Test Suites

DeepVerify features multi-layered automated test coverage spanning core API regression, authentication security, database resilience, and frontend Selenium browser suites.

### 1. Pytest Backend & API Verification Suite (TC01 – TC15)
Executes all 15 core verification test cases against an isolated in-memory test database:
```bash
python -m pytest tests/test_deepverify_suite.py -v
```
To generate an XML report:
```bash
python -m pytest tests/test_deepverify_suite.py --junitxml=test-reports/junit.xml -v
```

### 2. Headless Chrome Selenium Suite
Runs automated UI assertions directly against the active web server:
```bash
# Make sure the server is running on http://127.0.0.1:5000
python selenium_test/test_headless_chrome.py
```

### 3. Comprehensive Selenium E2E Suite (370+ Assertions)
Executes full DOM validation, responsive layout checks, and micro-interaction tests, generating an Excel audit report:
```bash
python selenium_test/run_tests.py
```
*Report generated:* `selenium_test/selenium_test_results.xlsx`

### 4. Authentication & Security Selenium Suite (310 Tests)
```bash
python selenium-tests/run_tests.py
```
*Report generated:* `selenium-tests/login_test_results.xlsx`

---

## 🔄 GitHub Actions CI/CD Pipeline

The `.github/workflows/deploy.yml` workflow triggers on every push and pull request to `main`:

```
┌────────────────────────────────────────────────────────┐
│               Push or PR to main branch                │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│     Job 1: Run Automated Tests (Pytest + Selenium)     │
│  - Set up Python 3.11 & Node.js 20                     │
│  - Install system dependencies & Headless Chrome       │
│  - Run Pytest test suite (TC01 - TC15)                 │
│  - Launch background server & health probe             │
│  - Execute Headless Chrome Selenium test suite         │
│  - Run 370+ Assertion Selenium E2E suite               │
│  - Upload test reports (XML & Excel) as artifacts      │
└──────────────────────────┬─────────────────────────────┘
                           │ (Runs ONLY if Job 1 passes)
                           ▼
┌────────────────────────────────────────────────────────┐
│    Job 2: Build & Deploy Web App to GitHub Pages       │
│  - Package production web assets (web/ -> site_dist)   │
│  - Upload Pages artifact (actions/upload-pages)        │
│  - Deploy to GitHub Pages (actions/deploy-pages)       │
└────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Directory Structure

```
.
├── .github/
│   └── workflows/
│       ├── deploy.yml            # Complete CI/CD: Automated Tests + GitHub Pages Deployment
│       └── tests.yml             # Dedicated Pytest CI Pipeline
├── app.py                        # Unified Flask Real-Time Server & REST API
├── ai_engine.py                  # Core Multi-Modal AI Detection Models
├── audio_classifier.py           # Audio Spectral & Neural Vocoder Classifier
├── image_authenticity_detector.py# 2D DFT Fourier & CNN Image Analyzer
├── video_authenticity_detector.py# Temporal Jitter & Face Consistency Analyzer
├── url_authenticity_detector.py  # Domain Forensics & Phishing Classification
├── auth.py                       # JWT Authentication, Bcrypt Hashing & RBAC
├── models.py                     # MongoDB Atlas & SQLite Database Layer
├── web/                          # Production Web Application (HTML5, CSS, JS)
│   ├── index.html                # Multi-modal detection UI & live dashboards
│   ├── style.css                 # Dark-mode cyber-defense design system
│   └── app.js                    # Web Audio, Webcam capture, & API integrations
├── tests/
│   ├── conftest.py               # Isolated test database fixture & summary hook
│   └── test_deepverify_suite.py  # 15 Automated Pytest Test Cases (TC01 - TC15)
├── selenium_test/
│   ├── run_tests.py              # 370+ Assertion Selenium runner & Excel exporter
│   ├── test_headless_chrome.py   # Live Headless Chrome WebDriver test suite
│   └── input.json                # Test case definition dataset
├── selenium-tests/               # Extended 310 Frontend Authentication E2E tests
├── .env.example                  # Sanitized environment configuration template
├── requirements.txt              # Production & test Python dependencies
└── README.md                     # Project documentation & execution guide
```

---

## 🔒 Security & Privacy Notice
- Sensitive configuration files (`.env`, local database files, browser cache) are untracked and excluded via `.gitignore`.
- Always store real production secrets in GitHub Repository Secrets (`Settings > Secrets and variables > Actions`).
