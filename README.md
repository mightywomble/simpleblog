# SimpleBlog

A modern, glass-themed blog application that dynamically fetches and displays markdown articles from GitHub repositories. Built with Flask and featuring a sleek, responsive design with Tailwind CSS.

## Description

SimpleBlog is a lightweight, client-side blog platform that transforms your GitHub repositories into a beautiful blog. It fetches markdown files from specified GitHub repositories and displays them as elegant blog posts with a modern glassy interface. Perfect for developers who want to showcase their documentation, tutorials, or articles stored in GitHub repositories.

## Features

### 🎨 Modern UI/UX
- **Glass-morphism Design**: Beautiful translucent glass effects with backdrop blur
- **Responsive Layout**: Works seamlessly on desktop, tablet, and mobile devices
- **Dark Gradient Background**: Animated blue-emerald-teal gradient with subtle animations
- **Smooth Animations**: Hover effects and transitions for enhanced user experience

### 📝 Content Management
- **GitHub Integration**: Automatically fetches markdown files from GitHub repositories
- **Multi-Repository Support**: Add multiple GitHub repositories as content sources
- **Recursive Directory Scanning**: Discovers markdown files in nested directories
- **Auto-tagging**: Uses directory structure for automatic post categorization
- **Rich Markdown Rendering**: Powered by Showdown.js for comprehensive markdown support

### 🔍 User Features
- **Real-time Search**: Search across titles, tags, and content
- **Article Modal**: Full-screen reading experience with enhanced typography
- **Like System**: User engagement with persistent like counts
- **Share Functionality**: Native sharing API support with clipboard fallback
- **Responsive Cards**: Beautiful post preview cards with truncated content

### 🛠 Admin Panel
- **Secure Login**: Password-protected admin access
- **Repository Management**: Add/remove GitHub repositories
- **Content Scanning**: Manual refresh of blog content
- **Blog Customization**: Change blog name and branding
- **Password Management**: Change admin password with security validation
- **Force Password Change**: Security feature for default password replacement

### 🔒 Security Features
- **Session Management**: Secure admin session handling
- **Password Validation**: Minimum length requirements and confirmation
- **Default Password Warning**: Forces password change on first login
- **Local Storage Encryption**: Client-side data persistence

## Setup

### Prerequisites
- Python 3.7+
- Flask
- Internet connection (for GitHub API access)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/simpleblog.git
   cd simpleblog
   ```

2. **Install dependencies**
   ```bash
   pip install flask
   ```

3. **Run the application**
   ```bash
   python app.py
   ```

4. **Access the blog**
   - Open your browser and navigate to `http://localhost:5055`
   - The application will be accessible on your local network at `http://your-ip:5055`

### First-Time Setup

1. **Admin Login**
   - Click the "Admin" button in the top right corner
   - Login with default credentials:
     - Username: `admin`
     - Password: `password`

2. **Change Default Password**
   - You'll be prompted to change the default password immediately
   - Choose a secure password (minimum 6 characters)

3. **Add GitHub Repositories**
   - In the admin panel, add your GitHub repositories
   - Format: `username/repository-name`
   - Example: `octocat/Hello-World`

4. **Scan for Articles**
   - Click "Scan for New Articles" to fetch markdown files
   - The system will recursively search for `.md` files

## Directory Structure

```
simpleblog/
├── app.py                 # Main Flask application
├── templates/
│   └── index.html        # Main HTML template with embedded CSS/JS
├── static/               # Static files (if any)
├── README.md            # This file
└── requirements.txt     # Python dependencies (optional)
```

### File Descriptions

- **`app.py`**: The main Flask application server that serves the blog interface
- **`templates/index.html`**: The complete single-page application containing:
  - HTML structure
  - Embedded CSS with glass-morphism styling
  - JavaScript for GitHub API integration
  - Admin panel functionality
  - Modal systems for articles and administration

## Usage

### Adding Content

1. **Create Markdown Files**: Store your blog posts as `.md` files in your GitHub repositories
2. **Organize with Directories**: Use subdirectories to automatically tag your posts
3. **Add Repository**: Use the admin panel to add the repository to your blog
4. **Scan Content**: Click "Scan for New Articles" to update your blog

### Content Organization Example

```
your-blog-repo/
├── tech/
│   ├── javascript-tips.md
│   └── python-guide.md
├── tutorials/
│   ├── flask-setup.md
│   └── git-basics.md
└── personal/
    └── my-journey.md
```

This structure will automatically create tags: `tech`, `tutorials`, and `personal`.

### Admin Features

- **Repository Management**: Add/remove GitHub repositories
- **Content Refresh**: Manually scan for new articles
- **Blog Customization**: Change blog name and appearance
- **Security**: Update admin password

## Troubleshooting

### Common Issues

#### 1. No Articles Displayed
**Problem**: Blog shows "No articles found" message

**Solutions**:
- Verify repository names are correct (format: `username/repo`)
- Ensure repositories are public or you have access
- Check that repositories contain `.md` files
- Click "Scan for New Articles" in admin panel
- Check browser console for API errors

#### 2. GitHub API Rate Limiting
**Problem**: Errors when fetching from multiple repositories

**Solutions**:
- GitHub API has rate limits for unauthenticated requests (60/hour)
- Wait for the rate limit to reset
- Consider using fewer repositories
- For production use, implement GitHub token authentication

#### 3. Admin Panel Access Issues
**Problem**: Cannot access admin panel or login fails

**Solutions**:
- Use correct default credentials: `admin` / `password`
- Clear browser localStorage if passwords are corrupted
- Check browser console for JavaScript errors
- Ensure you've changed the default password

#### 4. Styling Issues
**Problem**: Glass effects or animations not working

**Solutions**:
- Ensure modern browser with backdrop-filter support
- Check that Tailwind CSS is loading from CDN
- Verify internet connection for external resources
- Clear browser cache

#### 5. Flask Server Issues
**Problem**: Server won't start or connection refused

**Solutions**:
- Check that port 5055 is available
- Verify Flask is installed: `pip install flask`
- Run with: `python app.py`
- Check firewall settings for network access

### Browser Compatibility

**Supported Browsers**:
- Chrome 76+
- Firefox 103+
- Safari 14+
- Edge 79+

**Required Features**:
- ES6+ JavaScript support
- CSS backdrop-filter support
- Fetch API support

### Performance Tips

1. **Repository Size**: Large repositories with many files may take longer to scan
2. **Caching**: The app caches articles in localStorage for faster loading
3. **Network**: Ensure stable internet connection for GitHub API calls
4. **Browser**: Modern browsers perform better with glass effects

### Security Considerations

⚠️ **Important Security Notes**:

- This is a client-side application intended for personal/development use
- Admin passwords are stored in browser localStorage (not production-ready)
- For production deployment, implement server-side authentication
- Consider using GitHub tokens for API access in production
- HTTPS is recommended for any public deployment

### Getting Help

If you encounter issues not covered here:

1. Check browser console for error messages
2. Verify GitHub repository accessibility
3. Test with a simple repository first
4. Ensure all dependencies are installed
5. Check network connectivity

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source and available under the [MIT License](LICENSE).

---

**Made with ❤️ for the developer community**
