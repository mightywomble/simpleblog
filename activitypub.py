"""
ActivityPub integration for SimpleBlog
Enables Fediverse compatibility by making the blog an ActivityPub server
"""
import json
import requests
from datetime import datetime
from urllib.parse import urljoin
from flask import request, jsonify, url_for
import hashlib
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

class ActivityPubServer:
    def __init__(self, app, base_url):
        self.app = app
        self.base_url = base_url
        self.setup_routes()
        
    def setup_routes(self):
        """Setup ActivityPub routes"""
        
        @self.app.route('/.well-known/webfinger')
        def webfinger():
            """WebFinger endpoint for user discovery"""
            resource = request.args.get('resource')
            if resource and resource.startswith('acct:blog@'):
                return jsonify({
                    "subject": resource,
                    "links": [{
                        "rel": "self",
                        "type": "application/activity+json",
                        "href": f"{self.base_url}/users/blog"
                    }]
                })
            return jsonify({"error": "Resource not found"}), 404
            
        @self.app.route('/users/blog')
        def actor():
            """Actor endpoint - represents your blog as an ActivityPub actor"""
            return jsonify({
                "@context": "https://www.w3.org/ns/activitystreams",
                "type": "Person",
                "id": f"{self.base_url}/users/blog",
                "name": "My Blog",
                "preferredUsername": "blog",
                "summary": "AI-powered blog with GitHub integration",
                "inbox": f"{self.base_url}/users/blog/inbox",
                "outbox": f"{self.base_url}/users/blog/outbox",
                "followers": f"{self.base_url}/users/blog/followers",
                "following": f"{self.base_url}/users/blog/following",
                "publicKey": {
                    "id": f"{self.base_url}/users/blog#main-key",
                    "owner": f"{self.base_url}/users/blog",
                    "publicKeyPem": self.get_public_key()
                }
            })
            
        @self.app.route('/users/blog/outbox')
        def outbox():
            """Outbox endpoint - shows published articles as ActivityPub objects"""
            articles = get_articles_from_db()  # Your existing function
            
            activities = []
            for article in articles[:20]:  # Limit to recent articles
                activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "type": "Create",
                    "id": f"{self.base_url}/activities/{hashlib.md5(article['path'].encode()).hexdigest()}",
                    "actor": f"{self.base_url}/users/blog",
                    "published": datetime.now().isoformat(),
                    "object": {
                        "type": "Article",
                        "id": f"{self.base_url}/articles/{article['path']}",
                        "name": article['title'],
                        "content": article['content'][:500] + "...",
                        "url": f"{self.base_url}/articles/{article['path']}",
                        "attributedTo": f"{self.base_url}/users/blog"
                    }
                }
                activities.append(activity)
                
            return jsonify({
                "@context": "https://www.w3.org/ns/activitystreams",
                "type": "OrderedCollection",
                "totalItems": len(activities),
                "orderedItems": activities
            })
            
        @self.app.route('/users/blog/inbox', methods=['POST'])
        def inbox():
            """Inbox endpoint - receives ActivityPub activities (likes, follows, etc.)"""
            activity = request.get_json()
            
            if activity['type'] == 'Follow':
                # Handle new follower
                self.handle_follow(activity)
            elif activity['type'] == 'Like':
                # Handle like on article
                self.handle_like(activity)
            elif activity['type'] == 'Create' and activity['object']['type'] == 'Note':
                # Handle reply/comment
                self.handle_reply(activity)
                
            return jsonify({"status": "accepted"})
    
    def handle_follow(self, activity):
        """Handle follow activity from Fediverse"""
        follower = activity['actor']
        # Store follower in database
        # Send Accept activity back
        
    def handle_like(self, activity):
        """Handle like activity on blog posts"""
        article_url = activity['object']
        liker = activity['actor']
        # Store like in database
        # Update article like count
        
    def handle_reply(self, activity):
        """Handle replies/comments from Fediverse"""
        comment = activity['object']
        # Store comment in database
        # Associate with blog post

    def get_public_key(self):
        """Get RSA public key for ActivityPub signing"""
        # Generate or load from config
        return "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"

# Cross-posting function
def post_to_fediverse(article):
    """Post new article to Fediverse followers"""
    activity = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Create",
        "actor": f"{base_url}/users/blog",
        "object": {
            "type": "Article",
            "name": article['title'],
            "content": article['content'][:500] + "...",
            "url": f"{base_url}/articles/{article['path']}"
        }
    }
    
    # Send to all followers' inboxes
    followers = get_followers_from_db()
    for follower in followers:
        send_to_inbox(follower['inbox'], activity)
