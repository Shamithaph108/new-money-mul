"""
Vercel Python Handler for Flask Application
"""

from app import app

def handler(request):
    """Vercel Python handler function"""
    # Use Flask's test client to handle the request
    with app.test_client() as client:
        # Get the response from Flask
        response = client.get(request.path)
        
        # Return the response in Vercel's expected format
        return (
            response.data,
            response.status_code,
            dict(response.headers)
        )
