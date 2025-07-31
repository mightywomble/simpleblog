from flask import Flask, render_template, send_from_directory

# Initialize the Flask application
app = Flask(__name__, static_folder='static')

@app.route('/')
def index():
    """
    Renders the main blog page.
    """
    return render_template('index.html')

if __name__ == '__main__':
    # Runs the app on a local development server.
    # Debug=True allows for automatic reloading when changes are made.
    # host='0.0.0.0' makes it accessible from any IP address
    # port=5055 sets the specific port
    app.run(host='0.0.0.0', port=5055, debug=True)
