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
import base64
import logging
try:
    # Prefer the newer gemini-2.5-flash module
    import google.generativeai as genai
except ImportError:
    # Fallback to older google module
    import google.generativeai as genai
from PIL import Image
from io import BytesIO
import openai

# Bluesky integration will be imported after app creation

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('debug.log'),
        logging.StreamHandler()
    ]
)

# Configuration file path
CONFIG_FILE = 'config.json'
DEFAULT_PASSWORD = 'password'
ANALYTICS_DB = 'analytics.db'

# Thread lock for database operations
db_lock = Lock()

def init_db():
    """Initialize the analytics database and articles database"""
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
        
        # Create table for storing articles data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tag TEXT,
                repo TEXT,
                path TEXT UNIQUE,
                image_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

# Article database functions
def save_articles_to_db(articles, auto_post_to_bluesky=False):
    """Save or update articles in the database"""
    try:
        with db_lock:
            conn = sqlite3.connect(ANALYTICS_DB)
            cursor = conn.cursor()
            
            for article in articles:
                # Use INSERT OR REPLACE to handle both new and existing articles
                cursor.execute('''
                    INSERT OR REPLACE INTO articles 
                    (title, content, tag, repo, path, image_url, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    article['title'],
                    article['content'],
                    article['tag'],
                    article['repo'],
                    article['path'],
                    article.get('imageUrl'),
                    datetime.now().isoformat()
                ))
            
            conn.commit()
            conn.close()
            logging.info(f"✅ Saved {len(articles)} articles to database")
            
            # Auto-post new articles to Bluesky if enabled
            if auto_post_to_bluesky:
                try:
                    bluesky = BlueskyIntegration()
                    for article in articles:
                        bluesky.post_article(
                            title=article['title'],
                            content_preview=article['content'][:300],
                            article_url=f"/articles/{article['path']}",
                            image_url=article.get('imageUrl')
                        )
                except Exception as e:
                    logging.warning(f"⚠️ Failed to post to Bluesky: {e}")
            
            return True
    except Exception as e:
        logging.error(f"❌ Failed to save articles to database: {e}")
        return False

def clear_articles_from_db():
    """Clear all articles from the database"""
    try:
        with db_lock:
            conn = sqlite3.connect(ANALYTICS_DB)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM articles')
            
            conn.commit()
            conn.close()
            logging.info("✅ Cleared all articles from database")
            return True
    except Exception as e:
        logging.error(f"❌ Failed to clear articles from database: {e}")
        return False

def get_articles_from_db():
    """Retrieve all articles from the database"""
    try:
        with db_lock:
            conn = sqlite3.connect(ANALYTICS_DB)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT title, content, tag, repo, path, image_url
                FROM articles
                ORDER BY created_at DESC, updated_at DESC
            ''')
            
            articles = []
            for row in cursor.fetchall():
                articles.append({
                    'title': row[0],
                    'content': row[1],
                    'tag': row[2],
                    'repo': row[3],
                    'path': row[4],
                    'imageUrl': row[5],
                    'likes': 0  # Likes are still stored in localStorage for now
                })
            
            conn.close()
            logging.info(f"✅ Retrieved {len(articles)} articles from database")
            return articles
    except Exception as e:
        logging.error(f"❌ Failed to retrieve articles from database: {e}")
        return []

def update_article_image_in_db(path, image_url):
    """Update the image URL for a specific article in the database"""
    try:
        with db_lock:
            conn = sqlite3.connect(ANALYTICS_DB)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE articles 
                SET image_url = ?, updated_at = ?
                WHERE path = ?
            ''', (image_url, datetime.now().isoformat(), path))
            
            conn.commit()
            conn.close()
            logging.info(f"✅ Updated image URL for article at path: {path}")
            return True
    except Exception as e:
        logging.error(f"❌ Failed to update article image in database: {e}")
        return False

# Image cache directory
IMAGE_CACHE_DIR = 'static/generated_images'
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

# Initialize Gemini API
def init_gemini():
    """Initialize Gemini API with API key from config or environment"""
    logging.info("🔑 Starting Gemini API initialization")
    
    # First try to get from config
    config = load_config()
    api_key = None
    
    if config and config.get('gemini_api_key'):
        api_key = config['gemini_api_key']
        logging.info("✅ API key found in config file")
    else:
        # Fall back to environment variable
        api_key = os.environ.get('GEMINI_API_KEY')
        logging.info(f"Environment variable check: {'✅ Found' if api_key else '❌ Not found'}")
    
    if api_key:
        logging.info(f"🔐 API key loaded (starts with: {api_key[:10]}...)")
        try:
            genai.configure(api_key=api_key)
            logging.info("✅ Gemini API configured successfully")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to configure Gemini API: {e}")
            return False
    
    logging.warning("❌ No GEMINI_API_KEY found in config or environment variables")
    return False

def get_openai_client():
    """Get OpenAI client with API key from config or environment"""
    logging.info("🔑 Starting OpenAI API initialization")
    
    # First try to get from config
    config = load_config()
    api_key = None
    
    if config and config.get('openai_api_key'):
        api_key = config['openai_api_key']
        logging.info("✅ OpenAI API key found in config file")
    else:
        # Fall back to environment variable
        api_key = os.environ.get('OPENAI_API_KEY')
        logging.info(f"OpenAI environment variable check: {'✅ Found' if api_key else '❌ Not found'}")
    
    if api_key:
        logging.info(f"🔐 OpenAI API key loaded (starts with: {api_key[:10]}...)")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            logging.info("✅ OpenAI API configured successfully")
            return client
        except Exception as e:
            logging.error(f"❌ Failed to configure OpenAI API: {e}")
            return None
    
    logging.warning("❌ No OPENAI_API_KEY found in config or environment variables")
    return None

def generate_image_with_openai(title, content_preview=""):
    """Generate an actual image using OpenAI DALL-E"""
    logging.info(f"🎨 Starting OpenAI DALL-E image generation for: '{title}'")
    
    try:
        client = get_openai_client()
        if not client:
            logging.warning("❌ OpenAI API key not configured")
            return None
        
        # Create a hash for the title to use as filename
        title_hash = hashlib.md5(title.encode()).hexdigest()
        image_path = os.path.join(IMAGE_CACHE_DIR, f"dalle_{title_hash}.png")
        logging.info(f"📁 DALL-E image will be saved to: {image_path}")
        
        # Check if image already exists
        if os.path.exists(image_path):
            logging.info("♻️ DALL-E image already exists, returning cached version")
            return f"/static/generated_images/dalle_{title_hash}.png"
        
        # Create a prompt for DALL-E
        prompt = f"Create a modern, professional blog post thumbnail image for a tech article titled '{title}'. The image should be visually appealing with a clean, minimal design suitable for a technology blog. Use vibrant colors and modern graphics."
        if content_preview:
            prompt += f" Context: {content_preview[:200]}"
        
        logging.info(f"📝 Using DALL-E prompt: {prompt[:150]}...")
        
        # Generate image with DALL-E
        logging.info("🚀 Sending request to OpenAI DALL-E API...")
        
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="hd",
            n=1
        )
        
        image_url = response.data[0].url
        logging.info(f"✅ Received DALL-E image URL: {image_url[:50]}...")
        
        # Download and save the image
        logging.info("💾 Downloading and saving DALL-E image...")
        image_response = requests.get(image_url, timeout=30)
        image_response.raise_for_status()
        
        with open(image_path, 'wb') as f:
            f.write(image_response.content)
        
        logging.info("✅ DALL-E image downloaded and saved successfully")
        return f"/static/generated_images/dalle_{title_hash}.png"
        
    except Exception as e:
        logging.error(f"❌ Failed to generate DALL-E image for '{title}': {e}")
        import traceback
        logging.error(f"📋 DALL-E error traceback: {traceback.format_exc()}")
        return None

def generate_article_image(title, content_preview=""):
    """Generate an image for a blog article using OpenAI DALL-E or Gemini-enhanced placeholders"""
    logging.info(f"🖼️ Starting image generation for: '{title}'")
    
    try:
        # First, try OpenAI DALL-E for actual image generation
        logging.info("🎨 Attempting OpenAI DALL-E image generation...")
        dalle_image_url = generate_image_with_openai(title, content_preview)
        if dalle_image_url:
            logging.info(f"✅ Successfully generated DALL-E image: {dalle_image_url}")
            return dalle_image_url
        
        logging.info("⚠️ DALL-E generation failed or unavailable, trying Gemini-enhanced placeholder...")
        
        # Fall back to Gemini-enhanced placeholder
        if not init_gemini():
            logging.warning("❌ Gemini API key not configured, using basic placeholder")
            return get_placeholder_image(title)
        
        logging.info("✅ Gemini API initialized successfully")
        
        # Use Gemini text generation to create image descriptions
        logging.info("🤖 Creating Gemini model for text generation...")
        
        # Try different model names that might work (updated for Gemini 2.5)
        model_names_to_try = [
            'models/gemini-2.5-flash',
            'models/gemini-2.5-pro',
            'gemini-2.5-flash',
            'gemini-2.5-pro',
            'models/gemini-1.5-flash',
            'models/gemini-1.5-pro', 
            'models/gemini-pro',
            'gemini-1.5-flash',
            'gemini-1.5-pro',
            'gemini-pro'
        ]
        
        model = None
        for model_name in model_names_to_try:
            try:
                logging.info(f"🦪 Trying model: {model_name}")
                model = genai.GenerativeModel(model_name)
                logging.info(f"✅ Successfully created model: {model_name}")
                break
            except Exception as e:
                logging.warning(f"⚠️ Model {model_name} failed: {e}")
                continue
        
        if not model:
            logging.error("❌ Failed to create any Gemini model, using basic placeholder")
            return get_placeholder_image(title)

        # Create a prompt to generate an image description
        prompt = f"Create a detailed visual description for a thumbnail image for a blog post titled '{title}'. Describe colors, composition, and visual elements that would make an appealing tech blog thumbnail. Keep it concise but vivid."
        logging.info(f"📝 Using prompt: {prompt[:100]}...")

        # Generate description using Gemini
        logging.info("🚀 Sending request to Gemini text API...")
        try:
            response = model.generate_content(prompt)
            description = response.text
            logging.info(f"✅ Received description from Gemini: {description[:100]}...")
        except Exception as e:
            logging.error(f"❌ Failed to call Gemini API: {e}")
            return get_placeholder_image(title)

        # Create an enhanced placeholder with the AI description
        logging.info("🔍 Creating enhanced placeholder with AI description...")
        try:
            enhanced_image_url = create_enhanced_placeholder(title, description)
            if enhanced_image_url:
                logging.info(f"✅ Created enhanced placeholder image")
                return enhanced_image_url
        except Exception as e:
            logging.error(f"❌ Failed to create enhanced placeholder: {e}")
            return get_placeholder_image(title)
        
    except Exception as e:
        logging.error(f"❌ Unexpected error generating image for '{title}': {e}")
        import traceback
        logging.error(f"📋 Full traceback: {traceback.format_exc()}")
        return get_placeholder_image(title)

def get_placeholder_image(title):
    """Generate a simple placeholder image with the article title"""
    try:
        title_hash = hashlib.md5(title.encode()).hexdigest()
        image_path = os.path.join(IMAGE_CACHE_DIR, f"placeholder_{title_hash}.svg")
        
        # Check if placeholder already exists
        if os.path.exists(image_path):
            return f"/static/generated_images/placeholder_{title_hash}.svg"
        
        # Create a simple SVG placeholder
        # Generate a color based on the title hash
        color_hash = int(title_hash[:6], 16)
        hue = color_hash % 360
        
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="400" height="200" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:hsl({hue}, 70%, 60%);stop-opacity:1" />
      <stop offset="100%" style="stop-color:hsl({(hue + 60) % 360}, 70%, 40%);stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="400" height="200" fill="url(#grad1)" />
  <rect x="20" y="20" width="360" height="160" fill="rgba(255,255,255,0.1)" rx="10" />
  <text x="200" y="110" font-family="Arial, sans-serif" font-size="16" font-weight="bold" text-anchor="middle" fill="white" opacity="0.9">
    {title[:50]}{'...' if len(title) > 50 else ''}
  </text>
</svg>'''
        
        # Save the SVG file
        with open(image_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        
        return f"/static/generated_images/placeholder_{title_hash}.svg"
        
    except Exception as e:
        print(f"Error creating placeholder image for '{title}': {e}")
        return None

def create_enhanced_placeholder(title, ai_description):
    """Create an enhanced placeholder with AI-generated description elements"""
    try:
        title_hash = hashlib.md5((title + ai_description).encode()).hexdigest()
        image_path = os.path.join(IMAGE_CACHE_DIR, f"enhanced_{title_hash}.svg")
        
        # Check if enhanced placeholder already exists
        if os.path.exists(image_path):
            return f"/static/generated_images/enhanced_{title_hash}.svg"
        
        # Extract color themes from AI description (simple keyword matching)
        description_lower = ai_description.lower()
        
        # Default colors
        primary_hue = int(title_hash[:3], 16) % 360
        secondary_hue = (primary_hue + 120) % 360
        
        # Adjust colors based on description keywords
        if 'blue' in description_lower or 'ocean' in description_lower or 'sky' in description_lower:
            primary_hue = 210
        elif 'green' in description_lower or 'nature' in description_lower or 'forest' in description_lower:
            primary_hue = 120
        elif 'red' in description_lower or 'fire' in description_lower or 'energy' in description_lower:
            primary_hue = 0
        elif 'purple' in description_lower or 'violet' in description_lower:
            primary_hue = 270
        elif 'orange' in description_lower or 'sunset' in description_lower:
            primary_hue = 30
        
        # Adjust saturation and lightness based on description mood
        saturation = 70
        lightness = 50
        
        if 'bright' in description_lower or 'vibrant' in description_lower:
            saturation = 85
        elif 'dark' in description_lower or 'shadow' in description_lower:
            lightness = 30
        elif 'light' in description_lower or 'soft' in description_lower:
            lightness = 70
            saturation = 50
        
        # Create more sophisticated SVG with patterns
        pattern_elements = ''
        if 'tech' in description_lower or 'digital' in description_lower or 'code' in description_lower:
            pattern_elements = f'''
            <circle cx="350" cy="50" r="30" fill="hsla({primary_hue}, 50%, 80%, 0.3)" />
            <rect x="320" y="30" width="60" height="40" fill="none" stroke="hsla({primary_hue}, 50%, 80%, 0.5)" stroke-width="2" rx="5" />
            <path d="M30 150 Q50 130 70 150 T110 150" fill="none" stroke="hsla({secondary_hue}, 60%, 70%, 0.4)" stroke-width="3" />
            '''
        elif 'abstract' in description_lower or 'geometric' in description_lower:
            pattern_elements = f'''
            <polygon points="50,50 80,30 110,50 80,70" fill="hsla({primary_hue}, 60%, 70%, 0.4)" />
            <circle cx="320" cy="160" r="25" fill="hsla({secondary_hue}, 50%, 60%, 0.3)" />
            <rect x="300" y="50" width="40" height="40" fill="hsla({primary_hue}, 40%, 80%, 0.3)" transform="rotate(45 320 70)" />
            '''
        
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="400" height="200" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="mainGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:hsl({primary_hue}, {saturation}%, {lightness + 10}%);stop-opacity:1" />
      <stop offset="50%" style="stop-color:hsl({secondary_hue}, {saturation - 10}%, {lightness}%);stop-opacity:1" />
      <stop offset="100%" style="stop-color:hsl({primary_hue}, {saturation}%, {lightness - 10}%);stop-opacity:1" />
    </linearGradient>
    <radialGradient id="overlayGrad" cx="50%" cy="50%" r="50%">
      <stop offset="0%" style="stop-color:rgba(255,255,255,0.2);stop-opacity:1" />
      <stop offset="100%" style="stop-color:rgba(255,255,255,0);stop-opacity:1" />
    </radialGradient>
  </defs>
  <rect width="400" height="200" fill="url(#mainGrad)" />
  <rect width="400" height="200" fill="url(#overlayGrad)" />
  {pattern_elements}
  <rect x="20" y="20" width="360" height="160" fill="rgba(255,255,255,0.1)" stroke="rgba(255,255,255,0.3)" stroke-width="1" rx="10" />
  <text x="200" y="95" font-family="Arial, sans-serif" font-size="18" font-weight="bold" text-anchor="middle" fill="white" opacity="0.95">
    {title[:45]}{'...' if len(title) > 45 else ''}
  </text>
  <text x="200" y="125" font-family="Arial, sans-serif" font-size="11" text-anchor="middle" fill="rgba(255,255,255,0.7)">
    AI-Enhanced
  </text>
</svg>'''
        
        # Save the enhanced SVG file
        with open(image_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        
        logging.info(f"Created enhanced placeholder with themes from: {ai_description[:50]}...")
        return f"/static/generated_images/enhanced_{title_hash}.svg"
        
    except Exception as e:
        logging.error(f"Error creating enhanced placeholder for '{title}': {e}")
        return None

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

# API Route to get articles
@app.route('/api/articles', methods=['GET'])
def get_articles():
    articles = get_articles_from_db()
    return jsonify(articles)

# API Route to save articles
@app.route('/api/save-articles', methods=['POST'])
@require_auth
def save_articles():
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Articles array required'}), 400
    
    if save_articles_to_db(data):
        return jsonify({'success': True, 'count': len(data)})
    else:
        return jsonify({'error': 'Failed to save articles'}), 500

# API Route to clear and rescan articles
@app.route('/api/rescan-articles', methods=['POST'])
@require_auth
def rescan_articles():
    """Clear all articles and rescan repositories"""
    try:
        # Clear existing articles
        if not clear_articles_from_db():
            return jsonify({'error': 'Failed to clear existing articles'}), 500
        
        logging.info("🔄 Starting complete rescan of repositories")
        return jsonify({'success': True, 'message': 'Articles cleared, ready for rescan'})
    except Exception as e:
        logging.error(f"❌ Failed to rescan articles: {e}")
        return jsonify({'error': 'Failed to rescan articles'}), 500

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
        'session_timeout_hours': config.get('session_timeout_hours', 24),
        'has_gemini_api_key': bool(config.get('gemini_api_key')),
        'has_openai_api_key': bool(config.get('openai_api_key')),
        'has_bluesky_credentials': bool(config.get('bluesky_handle') and config.get('bluesky_app_password')),
        'bluesky_handle': config.get('bluesky_handle', '') if config.get('bluesky_handle') else ''
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

@app.route('/api/config/gemini-api-key', methods=['POST'])
@require_auth
def set_gemini_api_key():
    """Set Gemini API key"""
    logging.info("🔑 SET GEMINI API KEY ENDPOINT CALLED")
    
    data = request.get_json()
    logging.info(f"📋 Request data received: {bool(data and data.get('api_key'))}")
    
    if not data or not data.get('api_key'):
        logging.error("❌ No API key provided in request")
        return jsonify({'error': 'API key required'}), 400
    
    config = load_config()
    if not config:
        logging.error("❌ Failed to load config")
        return jsonify({'error': 'Configuration error'}), 500
    
    api_key = data['api_key'].strip()
    logging.info(f"🔐 API key received (length: {len(api_key)}, starts with: {api_key[:10]}...)")
    
    if len(api_key) < 10:  # Basic validation
        logging.error("❌ API key too short")
        return jsonify({'error': 'API key appears to be too short'}), 400
    
    # Update API key
    config['gemini_api_key'] = api_key
    logging.info("💾 Attempting to save config with API key...")
    
    if save_config(config):
        logging.info("✅ Config saved successfully with Gemini API key")
        return jsonify({'success': True})
    else:
        logging.error("❌ Failed to save config")
        return jsonify({'error': 'Failed to save configuration'}), 500

@app.route('/api/config/openai-api-key', methods=['POST'])
@require_auth
def set_openai_api_key():
    """Set OpenAI API key"""
    logging.info("🔑 SET OPENAI API KEY ENDPOINT CALLED")
    
    data = request.get_json()
    logging.info(f"📋 Request data received: {bool(data and data.get('api_key'))}")
    
    if not data or not data.get('api_key'):
        logging.error("❌ No API key provided in request")
        return jsonify({'error': 'API key required'}), 400
    
    config = load_config()
    if not config:
        logging.error("❌ Failed to load config")
        return jsonify({'error': 'Configuration error'}), 500
    
    api_key = data['api_key'].strip()
    logging.info(f"🔐 OpenAI API key received (length: {len(api_key)}, starts with: {api_key[:10]}...)")
    
    if len(api_key) < 10:  # Basic validation
        logging.error("❌ API key too short")
        return jsonify({'error': 'API key appears to be too short'}), 400
    
    # Update API key
    config['openai_api_key'] = api_key
    logging.info("💾 Attempting to save config with OpenAI API key...")
    
    if save_config(config):
        logging.info("✅ Config saved successfully with OpenAI API key")
        return jsonify({'success': True})
    else:
        logging.error("❌ Failed to save config")
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

@app.route('/api/generate-image', methods=['POST'])
@require_auth
def generate_image_endpoint():
    """Generate an image for a blog post"""
    logging.info("\n" + "="*50)
    logging.info("🔥 GENERATE IMAGE ENDPOINT CALLED 🔥")
    logging.info("🔥 THIS IS THE NEW CODE WITH ENHANCED LOGGING 🔥")
    logging.info("="*50 + "\n")
    
    data = request.get_json()
    logging.info(f"📋 Request data: {data}")
    
    if not data or not data.get('title'):
        logging.error("❌ ERROR: No title provided in request")
        return jsonify({'error': 'Title required'}), 400
    
    title = data['title']
    content_preview = data.get('content', '')
    logging.info(f"🎯 Generating image for title: '{title}'")
    
    # Try to generate with Gemini first, fall back to placeholder
    logging.info("📞 Calling generate_article_image function...")
    image_url = generate_article_image(title, content_preview)
    logging.info(f"↩️ generate_article_image returned: {image_url}")
    
    if not image_url:
        logging.warning("⚠️ Gemini generation failed, falling back to placeholder...")
        image_url = get_placeholder_image(title)
        logging.info(f"🔄 Placeholder image URL: {image_url}")
    
    if image_url:
        logging.info(f"✅ Returning success with image_url: {image_url}")
        return jsonify({'success': True, 'image_url': image_url})
    else:
        logging.error("❌ ERROR: Both Gemini and placeholder generation failed")
        return jsonify({'error': 'Failed to generate image'}), 500

@app.route('/api/generate-images-batch', methods=['POST'])
@require_auth
def generate_images_batch():
    """Generate images for multiple blog posts"""
    data = request.get_json()
    if not data or not data.get('articles'):
        return jsonify({'error': 'Articles array required'}), 400
    
    articles = data['articles']
    results = []
    
    for article in articles:
        if not article.get('title'):
            continue
            
        title = article['title']
        content_preview = article.get('content', '')
        
        # Try to generate with Gemini first, fall back to placeholder
        image_url = generate_article_image(title, content_preview)
        if not image_url:
            image_url = get_placeholder_image(title)
        
        results.append({
            'title': title,
            'image_url': image_url,
            'path': article.get('path', ''),
            'success': image_url is not None
        })
    
    return jsonify({'success': True, 'results': results})

@app.route('/')
def index():
    """
    Renders the main blog page.
    """
    # Track homepage visit
    track_visit('homepage')
    return render_template('index.html')

# Setup Bluesky integration
try:
    from bluesky_integration import setup_bluesky_routes
    setup_bluesky_routes(app)
    print("✅ Bluesky integration enabled")
except ImportError as e:
    print(f"⚠️ Bluesky integration not available: {e}")

print("🚀 FLASK APP STARTING WITH NEW CODE - VERSION 2.0 🚀")
print("🔧 Debug mode enabled, image generation configured")

if __name__ == '__main__':
    # Runs the app on a local development server.
    # Debug=True allows for automatic reloading when changes are made.
    # host='0.0.0.0' makes it accessible from any IP address
    # port=5055 sets the specific port
    app.run(host='0.0.0.0', port=5057, debug=True)
