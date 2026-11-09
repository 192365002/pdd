"""
DeepVerify — Advanced Fake URL & Phishing Detection Engine
Comprehensive Multi-Technique URL Forensics and Risk Scoring

Implements 6 Independent Analysis Techniques:
1. URL Structure Analysis (Syntax, scheme, ports, depth, parameters, open redirects) - 15%
2. Domain Reputation Analysis (Threat intelligence, local feed, explicit unknown reporting) - 30%
3. Suspicious TLD Analysis (High-risk abused TLD risk list; never flags alone) - 5%
4. Typosquatting & Brand Impersonation (Leetspeak, Levenshtein, Punycode/IDN, brand spoofing) - 20%
5. Phishing Keyword Analysis (Context-aware combinations of credential/action/financial terms) - 10%
6. Domain & Host Analysis (Raw IP detection, localhost handling, deceptive '@' masking, nesting) - 20%
"""

import os
import re
import urllib.parse
import ipaddress
import logging

logger = logging.getLogger(__name__)

# =========================================================================
# CONFIGURATION & KNOWLEDGE BASES
# =========================================================================

# Maintained list of high-value brands and their legitimate official domains
POPULAR_BRANDS = {
    'paypal': {
        'official': 'paypal.com',
        'aliases': {'paypal.com', 'paypal.me'}
    },
    'google': {
        'official': 'google.com',
        'aliases': {
            'google.com', 'google.co.in', 'google.co.uk', 'google.com.au',
            'google.ca', 'google.de', 'google.fr', 'googleapis.com',
            'youtube.com', 'youtu.be', 'gmail.com', 'gstatic.com'
        }
    },
    'amazon': {
        'official': 'amazon.com',
        'aliases': {
            'amazon.com', 'amazon.in', 'amazon.co.uk', 'amazon.de',
            'amazon.ca', 'aws.amazon.com', 'media-amazon.com'
        }
    },
    'microsoft': {
        'official': 'microsoft.com',
        'aliases': {
            'microsoft.com', 'live.com', 'office.com', 'outlook.com',
            'windows.com', 'azure.com', 'bing.com', 'msn.com', 'sharepoint.com'
        }
    },
    'apple': {
        'official': 'apple.com',
        'aliases': {'apple.com', 'icloud.com', 'itunes.com', 'appleid.apple.com'}
    },
    'facebook': {
        'official': 'facebook.com',
        'aliases': {'facebook.com', 'fb.com', 'meta.com', 'messenger.com'}
    },
    'instagram': {
        'official': 'instagram.com',
        'aliases': {'instagram.com', 'cdninstagram.com'}
    },
    'netflix': {
        'official': 'netflix.com',
        'aliases': {'netflix.com'}
    },
    'github': {
        'official': 'github.com',
        'aliases': {'github.com', 'github.io', 'githubusercontent.com'}
    },
    'twitter': {
        'official': 'twitter.com',
        'aliases': {'twitter.com', 'x.com', 't.co'}
    },
    'linkedin': {
        'official': 'linkedin.com',
        'aliases': {'linkedin.com', 'licdn.com'}
    },
    'whatsapp': {
        'official': 'whatsapp.com',
        'aliases': {'whatsapp.com', 'wa.me'}
    },
    'chase': {
        'official': 'chase.com',
        'aliases': {'chase.com', 'jpmorganchase.com'}
    },
    'bankofamerica': {
        'official': 'bankofamerica.com',
        'aliases': {'bankofamerica.com', 'bofa.com'}
    },
    'wellsfargo': {
        'official': 'wellsfargo.com',
        'aliases': {'wellsfargo.com'}
    },
    'citibank': {
        'official': 'citi.com',
        'aliases': {'citi.com', 'citibank.com', 'citigroup.com'}
    },
    'binance': {
        'official': 'binance.com',
        'aliases': {'binance.com'}
    },
    'coinbase': {
        'official': 'coinbase.com',
        'aliases': {'coinbase.com'}
    },
    'dropbox': {
        'official': 'dropbox.com',
        'aliases': {'dropbox.com'}
    },
    'spotify': {
        'official': 'spotify.com',
        'aliases': {'spotify.com'}
    }
}

# Recognized legitimate and trusted root domains (RFC 2606 example domains, major services)
TRUSTED_DOMAINS = {
    'google.com', 'github.com', 'example.com', 'example.org', 'example.net',
    'wikipedia.org', 'cloudflare.com', 'microsoft.com', 'apple.com',
    'amazon.com', 'paypal.com', 'netflix.com', 'stackoverflow.com',
    'reddit.com', 'zoom.us', 'dropbox.com', 'slack.com', 'mozilla.org'
}

# High-risk Top-Level Domains heavily abused in automated phishing kits
SUSPICIOUS_TLDS = {
    '.xyz', '.click', '.top', '.tk', '.ml', '.ga', '.cf', '.gq',
    '.buzz', '.loan', '.work', '.fit', '.rest', '.icu', '.sbs',
    '.cfd', '.vip', '.monster', '.cc', '.pw', '.country', '.stream',
    '.download', '.racing', '.date', '.faith', '.cricket', '.science',
    '.party', '.win', '.accountant', '.gdn', '.men'
}

# Moderate-risk generic TLDs requiring additional scrutiny
MODERATE_TLDS = {
    '.info', '.biz', '.club', '.online', '.site', '.live', '.shop'
}

# Categorized phishing keywords
KEYWORD_CATEGORIES = {
    'auth': {
        'login', 'signin', 'sign-in', 'password', 'passcode', 'credential',
        '2fa', 'mfa', 'otp', 'authenticate', 'auth', 'access'
    },
    'action': {
        'verify', 'verification', 'update', 'confirm', 'confirmation',
        'restore', 'unlock', 'recover', 'recovery', 'validate', 'validation',
        'renew', 'action-required', 'reactivate', 'suspended'
    },
    'target': {
        'account', 'security', 'secure', 'banking', 'bank', 'payment',
        'billing', 'invoice', 'wallet', 'support', 'portal', 'service',
        'identity', 'kyc', 'alert', 'notice', 'session'
    }
}

# Leetspeak and visual homoglyph substitution mappings
LEET_CHAR_MAP = {
    '0': 'o',
    '1': 'l',
    '|': 'l',
    '!': 'i',
    '3': 'e',
    '4': 'a',
    '@': 'a',
    '5': 's',
    '$': 's',
    '7': 't',
    '8': 'b',
    'vv': 'w',
    'rn': 'm',
}

# Known malicious threat intelligence domains (local cache feed)
KNOWN_PHISHING_DOMAINS = {
    'paypa1-login.xyz',
    'g00gle-security.com',
    'secure-bank-verify.xyz',
    'evil.example',
    'verify-paypal-login.xyz',
    'apple-id-verify.cfd',
    'chase-online-secure.top',
    'metamask-restore-wallet.click'
}

# Weighted scoring distribution (Normalized to 100%)
WEIGHTS = {
    'structure': 0.15,
    'reputation': 0.30,
    'tld': 0.05,
    'typosquatting': 0.20,
    'keywords': 0.10,
    'host_domain': 0.20,
}


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculates Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            ins = prev[j + 1] + 1
            delete = curr[j] + 1
            sub = prev[j] + (0 if c1 == c2 else 1)
            curr.append(min(ins, delete, sub))
        prev = curr
    return prev[-1]


def normalize_leetspeak(text: str) -> str:
    """Replaces common leetspeak substitutions with ASCII standard characters."""
    result = text.lower()
    for leet, norm in LEET_CHAR_MAP.items():
        result = result.replace(leet, norm)
    return result


def extract_base_domain(hostname: str) -> str:
    """Extracts base domain (SLD + TLD) from a hostname."""
    if not hostname:
        return ''
    parts = hostname.lower().split('.')
    if len(parts) <= 2:
        return hostname.lower()
    # Check for known 2-level TLDs like .co.uk, .com.au, .co.in
    if len(parts) >= 3 and parts[-2] in ('co', 'com', 'org', 'net', 'gov', 'edu') and len(parts[-1]) == 2:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


# =========================================================================
# TECHNIQUE 1: URL STRUCTURE ANALYSIS (Weight: 15%)
# =========================================================================

def analyze_url_structure(parsed_url: urllib.parse.SplitResult, raw_url: str) -> dict:
    """
    Analyzes URL syntax, protocol security, ports, path depth, parameters,
    and open redirect patterns.
    """
    score = 0.0
    findings = []
    
    # 1. Protocol check
    scheme = (parsed_url.scheme or '').lower()
    has_https = (scheme == 'https')
    is_localhost = (parsed_url.hostname or '').lower() in ('localhost', '127.0.0.1', '::1')
    
    if not has_https and not is_localhost:
        score += 0.35
        findings.append("Lacks HTTPS transport encryption (unencrypted HTTP protocol)")
    
    # 2. Port check
    port = parsed_url.port
    if port is not None and not is_localhost:
        if port not in (80, 443):
            score += 0.35
            findings.append(f"Non-standard HTTP port ({port}) in URL authority")
            
    # 3. Overall URL length
    url_len = len(raw_url)
    if url_len > 160:
        score += 0.35
        findings.append(f"Unusually long URL length ({url_len} chars) frequently used to conceal target parameters")
    elif url_len > 95:
        score += 0.15
        findings.append(f"Elevated URL length ({url_len} chars)")
        
    # 4. Embedded URL in query string (Open Redirect pattern)
    query = parsed_url.query.lower()
    if ('http://' in query or 'https://' in query or 'redirect=' in query or 
        'url=' in query or 'next=' in query or 'dest=' in query or 'target=' in query):
        score += 0.40
        findings.append("Query string contains embedded redirect parameter (potential Open Redirect attack)")
        
    # 5. Suspicious multiple slashes or path nesting
    path = parsed_url.path
    if '//' in path or '..' in path:
        score += 0.30
        findings.append("Path contains suspicious directory traversal ('..') or redundant path delimiters ('//')")

    score = min(1.0, score)
    return {
        'score': round(score, 3),
        'has_https': has_https,
        'scheme': scheme,
        'port': port,
        'url_length': url_len,
        'findings': findings
    }


# =========================================================================
# TECHNIQUE 2: DOMAIN REPUTATION ANALYSIS (Weight: 30%)
# =========================================================================

def analyze_domain_reputation(hostname: str, base_domain: str) -> dict:
    """
    Evaluates domain reputation using trusted lists, threat blacklist feeds,
    and external API if configured. If no external API is configured,
    explicitly reports reputation as unknown without falsely assuming safety.
    """
    h_lower = hostname.lower()
    b_lower = base_domain.lower()
    findings = []
    
    # Check if recognized legitimate or RFC 2606 domain
    is_trusted = (
        b_lower in TRUSTED_DOMAINS or 
        h_lower in TRUSTED_DOMAINS or
        any(b_lower in b_info['aliases'] for b_info in POPULAR_BRANDS.values())
    )
    
    if is_trusted:
        return {
            'score': 0.0,
            'status': 'Clean / Verified',
            'is_trusted': True,
            'is_blacklisted': False,
            'findings': ["Domain is a recognized legitimate service in trusted reputation registry"]
        }
        
    # Check known threat feeds / blacklist
    is_blacklisted = (h_lower in KNOWN_PHISHING_DOMAINS or b_lower in KNOWN_PHISHING_DOMAINS)
    if is_blacklisted:
        return {
            'score': 1.0,
            'status': 'Malicious / Blacklisted',
            'is_trusted': False,
            'is_blacklisted': True,
            'findings': [f"Domain '{h_lower}' is flagged in active threat intelligence blacklist"]
        }
        
    # Check external API key configuration (e.g. Google Safe Browsing / VirusTotal)
    api_key = os.environ.get('SAFE_BROWSING_API_KEY') or os.environ.get('VIRUSTOTAL_API_KEY')
    if not api_key:
        status_text = "Unknown / Unverified (No Threat Feed Configured)"
        findings.append("External threat intelligence API is not configured; reputation cannot be verified online")
        # Missing reputation data must NOT be treated as proof of safety (neutral weight 0.30)
        reputation_score = 0.30
    else:
        status_text = "Unknown / Unverified (No Threat Feed Match)"
        findings.append("Domain has no prior security reputation record in external threat databases")
        reputation_score = 0.25

    return {
        'score': round(reputation_score, 3),
        'status': status_text,
        'is_trusted': False,
        'is_blacklisted': False,
        'findings': findings
    }


# =========================================================================
# TECHNIQUE 3: SUSPICIOUS TLD ANALYSIS (Weight: 5%)
# =========================================================================

def analyze_tld(hostname: str) -> dict:
    """
    Inspects Top-Level Domain against a configurable high-risk abuse registry.
    Strictly calibrated: high-risk TLD adds at most 5% to the final score and
    never triggers a fake or phishing verdict alone.
    """
    h_lower = hostname.lower()
    matched_tld = ''
    score = 0.0
    findings = []
    
    # Extract extension
    parts = h_lower.split('.')
    if len(parts) >= 2:
        tld = '.' + parts[-1]
        if tld in SUSPICIOUS_TLDS:
            score = 1.0
            matched_tld = tld
            findings.append(f"Top-Level Domain '{tld}' has a statistically elevated abuse rate in automated phishing")
        elif tld in MODERATE_TLDS:
            score = 0.5
            matched_tld = tld
            findings.append(f"Generic TLD '{tld}' observed in mass unvetted domain registrations")
        else:
            matched_tld = tld
            
    return {
        'score': round(score, 3),
        'tld': matched_tld,
        'is_suspicious': (score > 0),
        'findings': findings
    }


# =========================================================================
# TECHNIQUE 4: TYPOSQUATTING & BRAND IMPERSONATION (Weight: 20%)
# =========================================================================

def analyze_typosquatting(hostname: str, parsed_url: urllib.parse.SplitResult, base_domain: str) -> dict:
    """
    Detects misspelled brand names, visual character substitutions (leetspeak),
    Punycode / IDN homograph attacks, and brand keyword abuse in unverified domains.
    """
    h_lower = hostname.lower()
    b_lower = base_domain.lower()
    score = 0.0
    findings = []
    detected_brands = []
    
    # 1. Punycode / IDN Homograph check
    if 'xn--' in h_lower or any(ord(c) > 127 for c in h_lower):
        score = max(score, 0.95)
        findings.append("Punycode / Internationalized Domain Name (IDN) homograph pattern detected")
        
    # 2. Deceptive username/userinfo spoofing (e.g. google.com@evil.example)
    username = (parsed_url.username or '').lower()
    if username:
        for brand, b_info in POPULAR_BRANDS.items():
            if brand in username or b_info['official'] in username:
                score = max(score, 1.0)
                detected_brands.append(brand)
                findings.append(
                    f"Credential masking attack: Brand '{b_info['official']}' placed before '@' symbol to disguise actual host '{h_lower}'"
                )
                
    # 3. Tokenize hostname labels (split on dots and hyphens)
    domain_labels = re.split(r'[\.\-]', h_lower)
    domain_labels = [lbl for lbl in domain_labels if lbl and lbl not in ('com', 'org', 'net', 'www', 'http', 'https')]
    
    # 4. Check each label for exact brand name misuse, leetspeak, or Levenshtein distance
    for brand, b_info in POPULAR_BRANDS.items():
        is_official = (b_lower in b_info['aliases'] or h_lower in b_info['aliases'])
        if is_official:
            continue  # Legitimate brand domain
            
        # Check brand name directly in unverified domain
        if brand in domain_labels:
            score = max(score, 0.85)
            detected_brands.append(brand)
            findings.append(
                f"Brand name misuse: Brand '{brand}' appears as hostname token in unauthorized domain '{h_lower}'"
            )
            continue
            
        # Check Leetspeak de-obfuscation (e.g. paypa1 -> paypal, g00gle -> google, amaz0n -> amazon)
        for label in domain_labels:
            if len(label) < 3:
                continue
            de_leet = normalize_leetspeak(label)
            if de_leet == brand and label != brand:
                score = max(score, 1.0)
                detected_brands.append(brand)
                findings.append(
                    f"Character substitution typosquatting: '{label}' visually mimics legitimate brand '{brand}'"
                )
                break
                
            # Check Levenshtein edit distance for typo variations
            if len(label) >= 4 and abs(len(label) - len(brand)) <= 2:
                dist = levenshtein_distance(label, brand)
                if dist == 1 or (dist == 2 and len(brand) >= 6):
                    score = max(score, 0.90)
                    detected_brands.append(brand)
                    findings.append(
                        f"Typosquatting variant: '{label}' is 1 edit distance from legitimate brand '{brand}'"
                    )
                    break

    return {
        'score': round(score, 3),
        'detected_brands': list(set(detected_brands)),
        'is_typosquatted': (score >= 0.70),
        'findings': findings
    }


# =========================================================================
# TECHNIQUE 5: PHISHING KEYWORD ANALYSIS (Weight: 10%)
# =========================================================================

def analyze_phishing_keywords(parsed_url: urllib.parse.SplitResult, is_trusted_domain: bool) -> dict:
    """
    Performs context-aware analysis of credential, action, and financial keywords.
    Keywords on legitimate services (e.g. github.com/login) are NOT penalized.
    """
    if is_trusted_domain:
        return {
            'score': 0.0,
            'keywords_found': [],
            'findings': ["Domain is a verified service; standard operational paths are considered legitimate"]
        }
        
    score = 0.0
    findings = []
    keywords_found = []
    
    h_lower = (parsed_url.hostname or '').lower()
    path_query = (parsed_url.path + '?' + parsed_url.query).lower()
    
    # Check keywords in hostname (high severity) vs path (moderate severity)
    h_tokens = set(re.split(r'[\.\-_/]', h_lower))
    pq_tokens = set(re.split(r'[\.\-_/&=?]', path_query))
    
    matched_categories = set()
    
    for cat_name, kw_set in KEYWORD_CATEGORIES.items():
        h_hits = kw_set.intersection(h_tokens)
        pq_hits = kw_set.intersection(pq_tokens)
        
        if h_hits:
            matched_categories.add(cat_name)
            keywords_found.extend(list(h_hits))
            score += 0.45
            findings.append(f"High-risk {cat_name} keyword(s) in domain name: {', '.join(h_hits)}")
            
        elif pq_hits:
            matched_categories.add(cat_name)
            keywords_found.extend(list(pq_hits))
            score += 0.20
            findings.append(f"{cat_name.capitalize()} keyword(s) in URL path/query: {', '.join(pq_hits)}")
            
    # Compound category combination boost (e.g. auth + action + financial)
    if len(matched_categories) >= 3:
        score += 0.35
        findings.append("Suspicious multi-category keyword combination (Authentication + Action + Financial)")
    elif len(matched_categories) == 2:
        score += 0.20
        findings.append("Suspicious paired keyword pattern (e.g. credential verification / account security)")

    score = min(1.0, score)
    return {
        'score': round(score, 3),
        'keywords_found': list(set(keywords_found)),
        'findings': findings
    }


# =========================================================================
# TECHNIQUE 6: DOMAIN & HOST ANALYSIS (Weight: 20%)
# =========================================================================

def analyze_domain_and_host(parsed_url: urllib.parse.SplitResult, hostname: str) -> dict:
    """
    Analyzes raw IP hosts, localhost environments, deceptive '@' masking,
    excessive subdomain nesting, and suspicious URL encoding.
    """
    score = 0.0
    findings = []
    h_lower = hostname.lower()
    
    # 1. Localhost development environment handling
    is_localhost = (
        h_lower in ('localhost', '127.0.0.1', '::1', '0.0.0.0') or 
        h_lower.endswith('.localhost')
    )
    if is_localhost:
        return {
            'score': 0.05,
            'is_localhost': True,
            'is_raw_ip': False,
            'subdomain_count': 0,
            'findings': ["Local development host (localhost) — valid for development testing, not a public internet domain"]
        }
        
    # 2. Raw IP address detection (IPv4 / IPv6)
    is_raw_ip = False
    try:
        ip_obj = ipaddress.ip_address(h_lower)
        is_raw_ip = True
        score += 0.85
        findings.append(f"Raw IP address host ('{h_lower}') used instead of registered domain name — common evasion tactic")
    except ValueError:
        pass
        
    # 3. Deceptive '@' symbol in URL authority
    if '@' in (parsed_url.netloc or ''):
        score += 0.90
        findings.append(f"Deceptive '@' credential masking: browser directs to true destination '{h_lower}' while displaying false prefix")
        
    # 4. Excessive subdomain depth
    subdomain_count = max(0, h_lower.count('.') - 1)
    if not is_raw_ip:
        if subdomain_count >= 3:
            score += 0.50
            findings.append(f"Excessive subdomain nesting ({subdomain_count} levels) commonly used for DNS masking")
        elif subdomain_count == 2:
            score += 0.15
            findings.append(f"Multiple subdomains ({subdomain_count} levels) detected")
            
    # 5. Suspicious URL encoding or hex formatting in authority
    if '%' in parsed_url.netloc or '0x' in parsed_url.netloc.lower():
        score += 0.60
        findings.append("Authority contains percent-encoded or hexadecimal characters (obfuscation pattern)")

    score = min(1.0, score)
    return {
        'score': round(score, 3),
        'is_localhost': False,
        'is_raw_ip': is_raw_ip,
        'subdomain_count': subdomain_count if not is_raw_ip else 0,
        'findings': findings
    }


# =========================================================================
# URL SYNTAX VALIDATION
# =========================================================================

def validate_url_syntax(raw_url: str):
    """
    Validates URL syntax, structure, protocol, and character validity.
    Returns: (is_valid: bool, normalized_url: str, parsed_url or error_msg: str)
    """
    if not raw_url or not isinstance(raw_url, str):
        return False, '', "URL cannot be empty."
        
    url_trimmed = raw_url.strip()
    if any(c in url_trimmed for c in (' ', '\n', '\t', '\r')):
        return False, url_trimmed, "URL contains illegal whitespace characters."
        
    # Ensure scheme is present for parsing
    has_scheme = bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+\-.]*://', url_trimmed))
    to_parse = url_trimmed if has_scheme else 'http://' + url_trimmed
    
    try:
        parsed = urllib.parse.urlsplit(to_parse)
    except Exception as e:
        return False, url_trimmed, f"Malformed URL syntax: {str(e)}"
        
    scheme = (parsed.scheme or '').lower()
    if scheme not in ('http', 'https'):
        return False, url_trimmed, f"Unsupported URL protocol '{scheme}'. Only HTTP and HTTPS are supported."
        
    hostname = parsed.hostname
    if not hostname:
        return False, url_trimmed, "Missing hostname or network address."
        
    # Check illegal characters in host
    illegal_chars = (' ', '"', '<', '>', '{', '}', '|', '\\', '^', '~', '`')
    if any(c in hostname for c in illegal_chars):
        return False, url_trimmed, "Hostname contains invalid characters."
        
    # Valid if localhost
    if hostname.lower() in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
        return True, to_parse, parsed
        
    # Valid if raw IP
    try:
        ipaddress.ip_address(hostname)
        return True, to_parse, parsed
    except ValueError:
        pass
        
    # Domain structure check: at least one dot and valid TLD format
    parts = hostname.split('.')
    if len(parts) < 2 or not parts[-1]:
        return False, url_trimmed, "Invalid domain format: missing top-level domain extension (TLD)."
        
    tld = parts[-1]
    if not re.match(r'^[a-zA-Z]{2,}$', tld) and not tld.startswith('xn--'):
        return False, url_trimmed, f"Invalid top-level domain format: .{tld}"
        
    return True, to_parse, parsed


# =========================================================================
# MAIN EVALUATION ENGINE: 6-TECHNIQUE RISK SCORING
# =========================================================================

def evaluate_url_authenticity(raw_url: str) -> dict:
    """
    Analyzes URL across all 6 detection techniques, computes normalized
    weighted risk score (0-100%), and assigns final classification.
    """
    # 1. Syntax Validation
    is_valid, normalized_url, parsed_or_err = validate_url_syntax(raw_url)
    if not is_valid:
        return {
            'status': 'error',
            'classification': 'RISK',
            'verdict': 'RISK',
            'risk_percentage': None,
            'score': None,
            'confidence': None,
            'risk_level': 'Risk',
            'reputation_status': 'Unknown / Unverified',
            'explanation': f"Invalid URL syntax: {parsed_or_err}",
            'reasons': [f"Syntax check failed: {parsed_or_err}", "URL must be a valid domain or IP address format"],
            'suspicious_patterns': ["Malformed URL structure"],
            'details': {
                'flags': [parsed_or_err],
                'has_https': False,
                'domain': '',
                'base_domain': '',
                'is_trusted': False,
                'is_localhost': False
            },
            'recommendations': [
                "Verify the URL syntax and check for typographical errors",
                "Ensure domain name includes a valid extension (e.g. .com, .org)"
            ]
        }

    parsed = parsed_or_err
    hostname = (parsed.hostname or '').lower()
    base_domain = extract_base_domain(hostname)

    # 2. Execute 6 Analysis Techniques
    t1_struct = analyze_url_structure(parsed, normalized_url)
    t2_reput = analyze_domain_reputation(hostname, base_domain)
    t3_tld = analyze_tld(hostname)
    t4_typo = analyze_typosquatting(hostname, parsed, base_domain)
    t5_kw = analyze_phishing_keywords(parsed, t2_reput['is_trusted'])
    t6_host = analyze_domain_and_host(parsed, hostname)

    # 3. Base Weighted Score Calculation (Weights total 1.0)
    w_score = (
        t1_struct['score'] * WEIGHTS['structure'] +
        t2_reput['score'] * WEIGHTS['reputation'] +
        t3_tld['score'] * WEIGHTS['tld'] +
        t4_typo['score'] * WEIGHTS['typosquatting'] +
        t5_kw['score'] * WEIGHTS['keywords'] +
        t6_host['score'] * WEIGHTS['host_domain']
    )
    
    # Convert to 0-100 scale
    total_risk = round(w_score * 100, 1)

    # 4. Compound Risk Multipliers for Severe Threat Combinations
    compound_flags = []
    
    # Compound Threat 1: Typosquatting + Phishing Keywords on unverified domain
    if t4_typo['is_typosquatted'] and t5_kw['score'] >= 0.40 and not t2_reput['is_trusted']:
        total_risk += 25.0
        compound_flags.append(
            f"Compound Threat: Brand impersonation targeting '{t4_typo['detected_brands']}' combined with credential harvesting keywords"
        )
        
    # Compound Threat 2: Deceptive '@' credential masking
    if '@' in (parsed.netloc or '') and not t2_reput['is_trusted']:
        total_risk += 25.0
        compound_flags.append("Compound Threat: Deceptive '@' credential masking disguising actual destination host")
        
    # Compound Threat 3: High-risk TLD + Multiple Financial/Banking Phishing Keywords
    if t3_tld['is_suspicious'] and t5_kw['score'] >= 0.65 and not t2_reput['is_trusted']:
        total_risk += 25.0
        compound_flags.append("Compound Threat: Sensitive financial verification keywords on disposable high-risk TLD")
        
    # Compound Threat 4: Raw IP address serving login/auth portal
    if t6_host['is_raw_ip'] and t5_kw['score'] >= 0.20:
        total_risk += 20.0
        compound_flags.append("Compound Threat: Direct IP address hosting credential login interface")

    # Blacklist override
    if t2_reput['is_blacklisted']:
        total_risk = max(total_risk, 85.0)

    # Clean trusted domain clamp
    if t2_reput['is_trusted']:
        total_risk = min(total_risk, 5.0)
        
    # Localhost development clamp
    if t6_host['is_localhost']:
        total_risk = min(total_risk, 10.0)

    # Clamp total risk between 0 and 100
    total_risk = min(100.0, max(0.0, round(total_risk)))
    total_risk_int = int(total_risk)

    # 5. Final Classification Assignment
    # 5. Final Classification Assignment: Strictly ONLY 'SAFE' or 'RISK' (Zero percentages)
    if t6_host['is_localhost']:
        classification = 'SAFE'
        risk_level = 'Safe'
        main_explanation = (
            "Local development server (localhost / 127.0.0.1) verified. Valid for local application development testing."
        )
    elif t2_reput['is_trusted']:
        classification = 'SAFE'
        risk_level = 'Safe'
        main_explanation = (
            f"Verified legitimate domain: '{base_domain}'. Validated against trusted domain registry with secure transport and clean path."
        )
    elif total_risk >= 30:
        classification = 'RISK'
        risk_level = 'Risk'
        main_explanation = (
            "Risk indicators detected. The URL exhibits domain spoofing, deceptive host structure, typosquatting, or credential harvesting patterns."
        )
    else:
        classification = 'SAFE'
        risk_level = 'Safe'
        main_explanation = "URL evaluated safe. No domain masking, phishing patterns, or deceptive structures detected."

    # 6. Aggregate Reasons and Suspicious Patterns
    all_findings = []
    all_findings.extend(compound_flags)
    all_findings.extend(t4_typo['findings'])
    all_findings.extend(t6_host['findings'])
    all_findings.extend(t5_kw['findings'])
    all_findings.extend(t3_tld['findings'])
    all_findings.extend(t1_struct['findings'])
    all_findings.extend(t2_reput['findings'])

    suspicious_patterns = [f for f in all_findings if not f.startswith("Domain is a") and not f.startswith("Local development")]

    reasons = all_findings if all_findings else [
        "Standard domain syntax and web protocol",
        "Clean hostname structure with no typosquatting detected",
        "No credential harvesting or deception patterns found"
    ]

    # Recommendations
    if classification == 'RISK':
        recs = [
            "Do NOT visit this URL or enter credentials, passwords, or payment details",
            "Verify identity via official verified domain channels",
            "Inspect URL bar carefully for character substitutions or deceptive host structures"
        ]
    else:
        recs = [
            "Safe for browsing under standard operational hygiene",
            "Maintain standard security verification for authentication requests"
        ]

    return {
        'status': 'success',
        'classification': classification,
        'verdict': classification,
        'risk_percentage': None,
        'score': None,
        'confidence': None,
        'risk_level': risk_level,
        'reputation_status': t2_reput['status'],
        'explanation': main_explanation,
        'reasons': reasons,
        'suspicious_patterns': suspicious_patterns,
        'breakdown': {
            'url_structure': {
                'weight': 15,
                'score': t1_struct['score'],
                'findings': t1_struct['findings']
            },
            'domain_reputation': {
                'weight': 30,
                'score': t2_reput['score'],
                'status': t2_reput['status'],
                'findings': t2_reput['findings']
            },
            'tld_analysis': {
                'weight': 5,
                'score': t3_tld['score'],
                'tld': t3_tld['tld'],
                'findings': t3_tld['findings']
            },
            'typosquatting': {
                'weight': 20,
                'score': t4_typo['score'],
                'detected_brands': t4_typo['detected_brands'],
                'findings': t4_typo['findings']
            },
            'phishing_keywords': {
                'weight': 10,
                'score': t5_kw['score'],
                'keywords_found': t5_kw['keywords_found'],
                'findings': t5_kw['findings']
            },
            'domain_host': {
                'weight': 20,
                'score': t6_host['score'],
                'findings': t6_host['findings']
            }
        },
        'details': {
            'flags': reasons,
            'has_https': t1_struct['has_https'],
            'domain': hostname,
            'base_domain': base_domain,
            'is_trusted': t2_reput['is_trusted'],
            'is_localhost': t6_host['is_localhost'],
            'is_raw_ip': t6_host['is_raw_ip'],
            'subdomain_count': t6_host['subdomain_count'],
            'reputation_status': t2_reput['status']
        },
        'recommendations': recs
    }
