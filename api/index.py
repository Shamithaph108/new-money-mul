"""
Vercel Python Handler for Flask Application
"""
import sys

# Initialize app at module level
from app import app as flask_app

def handler(request):
    """Vercel Python handler function"""
    try:
        # Simple test route
        if request.path == "/" or request.path == "":
            return (
                b"Hello from Money Muling Detection App",
                200,
                {"Content-Type": "text/html"}
            )
        
        # For API routes, use Flask
        with flask_app.test_client() as client:
            response = client.get(request.path)
            return (
                response.data,
                response.status_code,
                dict(response.headers)
            )
    except Exception as e:
        import traceback
        error_msg = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)
        return (
            error_msg.encode('utf-8'),
            500,
            {"Content-Type": "text/plain"}
        )
