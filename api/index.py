"""
Vercel Python Handler for Flask Application
"""

from app import app

def handler(request):
    """Vercel Python handler function"""
    return app.full_dispatch_request(request)
