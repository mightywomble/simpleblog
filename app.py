from flask import Flask, render_template, send_from_directory, request, jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import hashlib
import requests
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict, Counter
import sqlite3
from threading import Lock

# Configuration file path
CONFIG_FILE = 'config.json'
DEFAULT_PASSWORD = 'password'
ANALYTICS_DB = 'analytics.db'

# Thread lock for database operations
db_lock = Lock()

def init_db():
    """Initialize the analytics database"""
    with db_lock:
        conn = sqlite3.connect(ANALYTICS_DB)
        cursor = conn.cursor()
        
        # Create table for storing analytics data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                article TEXT,
                country TEXT,
                user_agent TEXT
            )
        ''')
        
        conn.commit()
        conn.close()

def get_country_from_ip(ip_address):
    """Get country from IP address using a free geolocation API"""
    try:
        # Use a free IP geolocation service
        response = requests.get(f'http://ip-api.com/json/{ip_address}', timeout=2)
        if response.status_code == 200:
            data = response.json()
            return data.get('country', 'Unknown')
    except:
        pass
    return 'Unknown'

def track_visit(article=None):
    """Track a visit to the site or specific article"""
    try:
        # Get visitor's IP address
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        if ip_address and ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()
        
        # Get country from IP
        country = get_country_from_ip(ip_address)
        
        # Get user agent
        user_agent = request.headers.get('User-Agent', '')
        
        # Store in database
        with db_lock:
            conn = sqlite3.connect(ANALYTICS_DB)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO analytics (ip_address, article, country, user_agent) VALUES (?, ?, ?, ?)',
                (ip_address, article, country, user_agent)
            )
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Error tracking visit: {e}")

init_db()

# Initialize the Flask application
app = Flask(__name__, static_folder='static')

# Configure for reverse proxy (HAProxy/nginx with HTTPS)
app.wsgi_app = ProxyFix(
    app.wsgi_app, 
    x_for=1,      # Trust 1 proxy for X-Forwarded-For
    x_proto=1,    # Trust 1 proxy for X-Forwarded-Proto (HTTP/HTTPS)
    x_host=1,     # Trust 1 proxy for X-Forwarded-Host
    x_prefix=1,   # Trust 1 proxy for X-Forwarded-Prefix
    x_port=1      # Trust 1 proxy for X-Forwarded-Port
)

# Generate a persistent secret key for session management
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Configure session cookies for HTTPS
use_https = os.environ.get('USE_HTTPS', 'false').lower() == 'true'
app.config.update(
    SESSION_COOKIE_SECURE=use_https,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24)
)


# Configuration management functions
def load_config():
    """Load configuration from JSON file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            
        # Validate required fields
        required_fields = ['blog_name', 'admin_username', 'admin_password_hash', 'repositories']
        for field in required_fields:
            if field not in config:
                print(f"Missing required field '{field}' in config.json")
                return None
                
        return config
        
    except FileNotFoundError:
        # Create default config if file doesn't exist
        print("Config file not found, creating default configuration...")
        default_config = {
            "blog_name": "My Blog",
            "admin_username": "admin",
            "admin_password_hash": generate_password_hash(DEFAULT_PASSWORD),
            "repositories": [],
            "session_timeout_hours": 24
        }
        if save_config(default_config):
            return default_config
        else:
            return None
            
    except json.JSONDecodeError as e:
        print(f"Error parsing config.json: {e}")
        return None
        
    except Exception as e:
        print(f"Error loading config: {e}")
        return None

def save_config(config):
    """Save configuration to JSON file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def require_auth(f):
    """Decorator to require authentication for admin endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        
        # Check session timeout
        config = load_config()
        if not config:
            return jsonify({'error': 'Configuration error'}), 500
            
        login_time = session.get('login_time')
        if login_time:
            login_datetime = datetime.fromisoformat(login_time)
            timeout_hours = config.get('session_timeout_hours', 24)
            if datetime.now() - login_datetime > timedelta(hours=timeout_hours):
                session.clear()
                return jsonify({'error': 'Session expired'}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# API Routes
@app.route('/api/login', methods=['POST'])
def login():
    """Admin login endpoint"""
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password required'}), 400
    
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration error'}), 500
    
    username = data['username']
    password = data['password']
    
    if (username == config['admin_username'] and 
        check_password_hash(config['admin_password_hash'], password)):
        
        session['authenticated'] = True
        session['login_time'] = datetime.now().isoformat()
        session.permanent = True
        
        # Check if using default password
        is_default_password = check_password_hash(config['admin_password_hash'], DEFAULT_PASSWORD)
        
        return jsonify({
            'success': True,
            'requires_password_change': is_default_password
        })
    else:
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    """Admin logout endpoint"""
    session.clear()
    return jsonify({'success': True})

@app.route('/api/config', methods=['GET'])
@require_auth
def get_config():
    """Get configuration (excluding sensitive data)"""
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration error'}), 500
    
    # Return config without password hash
    safe_config = {
        'blog_name': config.get('blog_name', 'My Blog'),
        'admin_username': config.get('admin_username', 'admin'),
        'repositories': config.get('repositories', []),
        'session_timeout_hours': config.get('session_timeout_hours', 24)
    }
    return jsonify(safe_config)

@app.route('/api/config/blog-name', methods=['POST'])
@require_auth
def update_blog_name():
    """Update blog name"""
    data = request.get_json()
    if not data or not data.get('blog_name'):
        return jsonify({'error': 'Blog name required'}), 400
    
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration error'}), 500
    
    config['blog_name'] = data['blog_name'].strip()
    
    if save_config(config):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to save configuration'}), 500

@app.route('/api/config/password', methods=['POST'])
@require_auth
def change_password():
    """Change admin password"""
    data = request.get_json()
    if not data or not data.get('current_password') or not data.get('new_password'):
        return jsonify({'error': 'Current and new password required'}), 400
    
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration error'}), 500
    
    # Verify current password
    if not check_password_hash(config['admin_password_hash'], data['current_password']):
        return jsonify({'error': 'Current password is incorrect'}), 400
    
    # Validate new password
    new_password = data['new_password']
    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    
    # Update password
    config['admin_password_hash'] = generate_password_hash(new_password)
    
    if save_config(config):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to save configuration'}), 500

@app.route('/api/repositories', methods=['GET'])
@require_auth
def get_repositories():
    """Get list of repositories"""
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration error'}), 500
    
    return jsonify({'repositories': config.get('repositories', [])})

@app.route('/api/repositories', methods=['POST'])
@require_auth
def add_repository():
    """Add a repository"""
    data = request.get_json()
    if not data or not data.get('repository'):
        return jsonify({'error': 'Repository required'}), 400
    
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration error'}), 500
    
    repo = data['repository'].strip()
    repositories = config.get('repositories', [])
    
    if repo not in repositories:
        repositories.append(repo)
        config['repositories'] = repositories
        
        if save_config(config):
            return jsonify({'success': True, 'repositories': repositories})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    else:
        return jsonify({'error': 'Repository already exists'}), 400

@app.route('/api/repositories/<int:index>', methods=['DELETE'])
@require_auth
def remove_repository(index):
    """Remove a repository by index"""
    config = load_config()
    if not config:
        return jsonify({'error': 'Configuration error'}), 500
    
    repositories = config.get('repositories', [])
    
    if 0 <= index < len(repositories):
        repositories.pop(index)
        config['repositories'] = repositories
        
        if save_config(config):
            return jsonify({'success': True, 'repositories': repositories})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    else:
        return jsonify({'error': 'Invalid repository index'}), 400

@app.route('/api/public/config', methods=['GET'])
def get_public_config():
    """Get public configuration (blog name and repositories) without authentication"""
    config = load_config()
    if not config:
        # Return defaults if config fails to load
        return jsonify({
            'blog_name': 'My Blog',
            'repositories': []
        })
    
    # Return only public information
    public_config = {
        'blog_name': config.get('blog_name', 'My Blog'),
        'repositories': config.get('repositories', [])
    }
    return jsonify(public_config)

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Check authentication status"""
    is_authenticated = session.get('authenticated', False)
    
    if is_authenticated:
        # Check if session is still valid
        config = load_config()
        login_time = session.get('login_time')
        
        if config and login_time:
            login_datetime = datetime.fromisoformat(login_time)
            timeout_hours = config.get('session_timeout_hours', 24)
            
            if datetime.now() - login_datetime > timedelta(hours=timeout_hours):
                session.clear()
                is_authenticated = False
    
    return jsonify({'authenticated': is_authenticated})

# Analytics endpoints
@app.route('/api/analytics/stats', methods=['GET'])
@require_auth
def get_analytics_stats():
    """Get comprehensive analytics statistics"""
    try:
        with db_lock:
            conn = sqlite3.connect(ANALYTICS_DB)
            cursor = conn.cursor()
            
            # Total hits
            cursor.execute('SELECT COUNT(*) FROM analytics')
            total_hits = cursor.fetchone()[0]
            
            # Unique visitors (based on IP)
            cursor.execute('SELECT COUNT(DISTINCT ip_address) FROM analytics')
            unique_visitors = cursor.fetchone()[0]
            
            # Top 10 articles
            cursor.execute('''
                SELECT article, COUNT(*) as views, 
                       GROUP_CONCAT(DISTINCT country) as countries
                FROM analytics 
                WHERE article IS NOT NULL AND article != ''
                GROUP BY article 
                ORDER BY views DESC 
                LIMIT 10
            ''')
            top_articles = [{
                'article': row[0],
                'views': row[1],
                'countries': row[2].split(',') if row[2] else []
            } for row in cursor.fetchall()]
            
            # Top 10 countries
            cursor.execute('''
                SELECT country, COUNT(*) as visits
                FROM analytics 
                WHERE country != 'Unknown'
                GROUP BY country 
                ORDER BY visits DESC 
                LIMIT 10
            ''')
            top_countries = [{
                'country': row[0],
                'visits': row[1]
            } for row in cursor.fetchall()]
            
            # Recent activity (last 30 days by day)
            cursor.execute('''
                SELECT DATE(timestamp) as date, COUNT(*) as visits
                FROM analytics 
                WHERE timestamp >= datetime('now', '-30 days')
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
            ''')
            daily_stats = [{
                'date': row[0],
                'visits': row[1]
            } for row in cursor.fetchall()]
            
            conn.close()
            
            return jsonify({
                'total_hits': total_hits,
                'unique_visitors': unique_visitors,
                'top_articles': top_articles,
                'top_countries': top_countries,
                'daily_stats': daily_stats
            })
            
    except Exception as e:
        print(f"Error getting analytics: {e}")
        return jsonify({'error': 'Failed to get analytics'}), 500

@app.route('/api/track', methods=['POST'])
def track_article_visit():
    """Track a visit to a specific article"""
    data = request.get_json()
    article = data.get('article') if data else None
    
    # Track the visit
    track_visit(article)
    
    return jsonify({'success': True})

@app.route('/')
def index():
    """
    Renders the main blog page.
    """
    # Track homepage visit
    track_visit('homepage')
    return render_template('index.html')

if __name__ == '__main__':
    # Runs the app on a local development server.
    # Debug=True allows for automatic reloading when changes are made.
    # host='0.0.0.0' makes it accessible from any IP address
    # port=5055 sets the specific port
    app.run(host='0.0.0.0', port=5057, debug=True)
