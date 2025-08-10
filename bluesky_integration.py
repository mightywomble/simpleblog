"""
Bluesky integration for SimpleBlog
Handles cross-posting and fetching engagement data from Bluesky
"""
import requests
import json
from datetime import datetime, timezone
import logging
import re

class BlueskyIntegration:
    def __init__(self):
        self.api_base = "https://bsky.social/xrpc"
        self.session = None
        self.config = self.load_config()
        
    def authenticate(self):
        """Authenticate with Bluesky using stored credentials"""
        if not self.config or not self.config.get('bluesky_handle') or not self.config.get('bluesky_app_password'):
            logging.warning("Bluesky credentials not configured")
            return False
            
        try:
            response = requests.post(
                f"{self.api_base}/com.atproto.server.createSession",
                json={
                    "identifier": self.config['bluesky_handle'],
                    "password": self.config['bluesky_app_password']
                }
            )
            
            if response.status_code == 200:
                self.session = response.json()
                logging.info("✅ Authenticated with Bluesky successfully")
                return True
            else:
                logging.error(f"❌ Bluesky authentication failed: {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Bluesky authentication error: {e}")
            return False
    
    def post_article(self, title, content_preview, article_url, image_url=None):
        """Post a new article to Bluesky"""
        if not self.authenticate():
            return None
            
        try:
            # Load public_base_url for proper links
            link = (article_url or '').strip()
            try:
                cfg = self.load_config()
                base = (cfg or {}).get('public_base_url')
                if base:
                    # If client passed a hash-only URL, rebuild fully
                    if link.startswith('#') or link.startswith('/'):
                        link = f"{base}{link}"
            except Exception:
                pass

            # Build hashtags: keep previous defaults and merge with provided example, deduplicated
            default_tags = ["#daveknowstech", "#blog", "#blogpost", "#tech", "#techblog"]
            example_tags = ["#vibecode", "#ai", "#ssh", "#tech", "#ssh", "#daveknowstech"]
            seen = set()
            merged_tags = []
            for tag in default_tags + example_tags:
                if tag not in seen:
                    seen.add(tag)
                    merged_tags.append(tag)
            hashtags_line = " ".join(merged_tags)

            summary = (title or '').strip()

            # Compose multiline template:
            # Line 1: summary/title
            # Line 2: Read more: <URL>
            # Line 3: hashtags
            def build_text(s, tags_str):
                parts = []
                if s:
                    parts.append(s)
                if link:
                    parts.append(f"Read more: {link}")
                if tags_str:
                    parts.append(tags_str)
                return "\n\n".join(parts)

            post_text = build_text(summary, hashtags_line)
            max_len = 300

            # If too long, first drop trailing hashtags one by one, then trim summary with ellipsis
            if len(post_text) > max_len:
                tags = merged_tags.copy()
                while len(post_text) > max_len and tags:
                    tags.pop()  # drop last tag
                    post_text = build_text(summary, " ".join(tags))
                if len(post_text) > max_len:
                    # Need to trim the summary to fit within the remaining budget
                    # Keep link and whatever tags remain if possible
                    remaining_tags = " ".join(tags)
                    # Compute fixed portion length when title is empty
                    fixed_text = build_text("", remaining_tags)
                    # If both link and tags absent, fixed_text may be empty; account for separators when title exists
                    # We'll rebuild iteratively trimming the summary
                    if not fixed_text:
                        # Only summary present; trim directly
                        if len(summary) > max_len:
                            post_text = summary[:max_len-1] + '…'
                        else:
                            post_text = summary
                    else:
                        # We will include summary and fixed_text separated by two newlines
                        # Reserve for "\n\n" separator between summary and fixed_text
                        sep = "\n\n"
                        budget = max_len - (len(fixed_text) + len(sep))
                        if budget <= 0:
                            # No room for summary; keep only fixed_text, and if still too long, trim tags already handled
                            post_text = fixed_text[:max_len]
                        else:
                            trimmed_summary = summary if len(summary) <= budget else (summary[:max(0, budget-1)] + '…')
                            post_text = trimmed_summary + sep + fixed_text

            # Build facets for links and hashtags so they are clickable
            facets = []
            
            # Helper: build UTF-8 byte position map for the text
            byte_pos = [0]
            for ch in post_text:
                byte_pos.append(byte_pos[-1] + len(ch.encode('utf-8')))
            def to_bytes(char_start, char_end):
                return byte_pos[char_start], byte_pos[char_end]

            # Link facet, if a link is present in the composed text
            if link:
                link_start = post_text.find(link)
                if link_start != -1:
                    link_end = link_start + len(link)
                    b_start, b_end = to_bytes(link_start, link_end)
                    facets.append({
                        "index": {"byteStart": b_start, "byteEnd": b_end},
                        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}]
                    })

            # Hashtag facets: annotate each #tag sequence
            for m in re.finditer(r"(?<!\w)#([A-Za-z0-9_]+)", post_text):
                tag_text = m.group(0)  # includes '#'
                tag = m.group(1)       # without '#'
                start = m.start()
                end = m.end()
                b_start, b_end = to_bytes(start, end)
                facets.append({
                    "index": {"byteStart": b_start, "byteEnd": b_end},
                    "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]
                })

            # Create the record with valid RFC-3339/ISO-8601 UTC timestamp
            created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
            record = {
                "$type": "app.bsky.feed.post",
                "text": post_text,
                "createdAt": created_at,
            }
            if facets:
                record["facets"] = facets
            
            # Post to Bluesky (with facets for rich text)
            response = requests.post(
                f"{self.api_base}/com.atproto.repo.createRecord",
                headers={
                    "Authorization": f"Bearer {self.session['accessJwt']}",
                    "Content-Type": "application/json"
                },
                json={
                    "repo": self.session["did"],
                    "collection": "app.bsky.feed.post",
                    "record": record
                }
            )
            
            if response.status_code == 200:
                post_data = response.json()
                logging.info(f"✅ Posted to Bluesky: {title}")
                return post_data['uri']
            else:
                logging.error(f"❌ Failed to post to Bluesky: {response.text}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Error posting to Bluesky: {e}")
            return None
    
    def upload_image(self, image_url):
        """Upload image to Bluesky for embedding"""
        try:
            # Download the image
            img_response = requests.get(image_url, timeout=10)
            if img_response.status_code != 200:
                return None
                
            # Upload to Bluesky
            upload_response = requests.post(
                f"{self.api_base}/com.atproto.repo.uploadBlob",
                headers={
                    "Authorization": f"Bearer {self.session['accessJwt']}",
                    "Content-Type": img_response.headers.get('content-type', 'image/jpeg')
                },
                data=img_response.content
            )
            
            if upload_response.status_code == 200:
                return upload_response.json()['blob']
            return None
            
        except Exception as e:
            logging.error(f"❌ Error uploading image to Bluesky: {e}")
            return None
    
    def get_post_engagement(self, post_uri):
        """Get engagement stats for a Bluesky post"""
        try:
            response = requests.get(
                f"{self.api_base}/com.atproto.repo.getRecord",
                params={
                    "repo": self.session["did"],
                    "collection": "app.bsky.feed.post",
                    "rkey": post_uri.split('/')[-1]
                },
                headers={
                    "Authorization": f"Bearer {self.session['accessJwt']}"
                }
            )
            
            if response.status_code == 200:
                post_data = response.json()
                
                # Get thread view for engagement stats
                thread_response = requests.get(
                    f"{self.api_base}/app.bsky.feed.getPostThread",
                    params={"uri": post_uri},
                    headers={"Authorization": f"Bearer {self.session['accessJwt']}"}
                )
                
                if thread_response.status_code == 200:
                    thread_data = thread_response.json()
                    post = thread_data['thread']['post']
                    
                    return {
                        "likes": post.get('likeCount', 0),
                        "reposts": post.get('repostCount', 0),
                        "replies": post.get('replyCount', 0)
                    }
            
            return {"likes": 0, "reposts": 0, "replies": 0}
            
        except Exception as e:
            logging.error(f"❌ Error getting Bluesky engagement: {e}")
            return {"likes": 0, "reposts": 0, "replies": 0}
    
    def get_post_replies(self, post_uri):
        """Get replies to a Bluesky post for displaying as comments"""
        try:
            response = requests.get(
                f"{self.api_base}/app.bsky.feed.getPostThread",
                params={
                    "uri": post_uri,
                    "depth": 2  # Get replies and their replies
                },
                headers={
                    "Authorization": f"Bearer {self.session['accessJwt']}"
                }
            )
            
            if response.status_code == 200:
                thread_data = response.json()
                replies = []
                
                def extract_replies(thread_item):
                    if 'replies' in thread_item:
                        for reply in thread_item['replies']:
                            if 'post' in reply:
                                post = reply['post']
                                replies.append({
                                    'author': {
                                        'displayName': post['author'].get('displayName', ''),
                                        'handle': post['author']['handle'],
                                        'avatar': post['author'].get('avatar', '')
                                    },
                                    'text': post['record']['text'],
                                    'createdAt': post['record']['createdAt'],
                                    'uri': post['uri']
                                })
                                # Recursively get nested replies
                                extract_replies(reply)
                
                if 'thread' in thread_data and 'replies' in thread_data['thread']:
                    extract_replies(thread_data['thread'])
                
                return replies
                
        except Exception as e:
            logging.error(f"❌ Error getting Bluesky replies: {e}")
            return []

    def load_config(self):
        """Load configuration from JSON file"""
        try:
            with open('config.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
            
    def save_config(self, config):
        """Save configuration to JSON file"""
        try:
            with open('config.json', 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            logging.error(f"Error saving config: {e}")
            return False

# Integration functions for app.py
def setup_bluesky_routes(app):
    """Add Bluesky-related routes to the Flask app"""
    from flask import request, jsonify
    
    def load_config():
        """Load configuration from JSON file"""
        try:
            with open('config.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
    
    def save_config(config):
        """Save configuration to JSON file"""
        try:
            with open('config.json', 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            logging.error(f"Error saving config: {e}")
            return False
    
    @app.route('/api/config/bluesky', methods=['POST'])
    def set_bluesky_config():
        """Configure Bluesky credentials"""
        from app import require_auth
        from flask import session
        
        # Check authentication
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        
        data = request.get_json()
        if not data or not data.get('handle') or not data.get('app_password'):
            return jsonify({'error': 'Handle and app password required'}), 400
        
        config = load_config()
        if not config:
            return jsonify({'error': 'Configuration error'}), 500
        
        config['bluesky_handle'] = data['handle']
        config['bluesky_app_password'] = data['app_password']
        
        if save_config(config):
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    
    @app.route('/api/bluesky/post-article', methods=['POST'])
    def post_article_to_bluesky():
        """Post an article to Bluesky"""
        from flask import session
        
        # Check authentication
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        
        data = request.get_json()
        if not data or not data.get('title'):
            return jsonify({'error': 'Title required'}), 400
        
        bluesky = BlueskyIntegration()
        post_uri = bluesky.post_article(
            title=data['title'],
            content_preview=data.get('content', ''),
            article_url=data.get('url', ''),
            image_url=data.get('image_url')
        )
        
        if post_uri:
            return jsonify({'success': True, 'post_uri': post_uri})
        else:
            return jsonify({'error': 'Failed to post to Bluesky'}), 500
    
    @app.route('/api/bluesky/stats/<path:article_path>')
    def get_article_bluesky_stats(article_path):
        """Get Bluesky engagement stats for an article"""
        # Look up the Bluesky post URI for this article
        # This would require storing the mapping when you post
        bluesky = BlueskyIntegration()
        post_uri = get_bluesky_post_uri_for_article(article_path)
        
        if post_uri:
            stats = bluesky.get_post_engagement(post_uri)
            return jsonify(stats)
        
        return jsonify({"likes": 0, "reposts": 0, "replies": 0})
    
    @app.route('/api/bluesky/test-connection', methods=['POST'])
    def test_bluesky_connection():
        """Test Bluesky credentials"""
        from flask import session
        
        # Check authentication
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        
        bluesky = BlueskyIntegration()
        success = bluesky.authenticate()
        
        if success:
            return jsonify({'success': True, 'message': 'Bluesky connection successful!'})
        else:
            return jsonify({'error': 'Failed to connect to Bluesky. Check your credentials.'})

def get_bluesky_post_uri_for_article(article_path):
    """Get the Bluesky post URI for an article path"""
    # You'd need to store this mapping in your database
    # when articles are posted to Bluesky
    return None
