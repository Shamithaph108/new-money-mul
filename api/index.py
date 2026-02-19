"""
Vercel Python Handler for Flask Application
"""
import sys

def handler(request):
    """Vercel Python handler function"""
    try:
        from app import app
        
        # Use Flask's test client
        with app.test_client() as client:
            response = client.get(request.path)
            
            return (
                response.data,
                response.status_code,
                dict(response.headers)
            )
    except Exception as e:
        # Return error details
        import traceback
        error_msg = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)
        return (
            error_msg.encode('utf-8'),
            500,
            {"Content-Type": "text/plain"}
        )
