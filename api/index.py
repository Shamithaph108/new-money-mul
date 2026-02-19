"""
Vercel Python Handler for Flask Application
"""

from app import app

def handler(request):
    """Vercel Python handler function"""
    # Use Flask app directly as WSGI app
    return app(request.environ, request.start_response)
