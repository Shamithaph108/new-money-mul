"""
Vercel Python Handler for Flask Application
"""
import sys

def handler(request):
    """Vercel Python handler function"""
    try:
        from app import app
        
        # Use Flask's test client to handle the request
        with app.test_client() as client:
            # Make the request to Flask
            response = client.get(request.path)
            
            # Return the response in Vercel's expected format
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
