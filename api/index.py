"""
Vercel Python Handler for Flask Application
"""
import sys

def handler(request):
    """Vercel Python handler function"""
    try:
        from app import app
        
        # Create a mock WSGI environment from the Vercel request
        environ = {
            'REQUEST_METHOD': request.method,
            'SCRIPT_NAME': '',
            'PATH_INFO': request.path,
            'QUERY_STRING': request.query_string.decode('utf-8'),
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': '5000',
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'HTTP_HOST': request.headers.get('host', 'localhost'),
            'wsgi.input': None,
            'wsgi.errors': sys.stderr,
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': 'https',
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': True,
        }
        
        # Add headers
        for header in request.headers:
            key = 'HTTP_' + header.upper().replace('-', '_')
            environ[key] = request.headers[header]
        
        # Collect response
        response_data = []
        
        def start_response(status, headers):
            response_data.append(status)
            response_data.append(headers)
            return lambda x: None
        
        # Call the Flask app as WSGI
        result = app(environ, start_response)
        
        # Combine the result
        body = b''.join(result)
        
        # Parse status code
        status = response_data[0]
        status_code = int(status.split()[0])
        
        # Parse headers
        headers = dict(response_data[1])
        
        return body, status_code, headers
        
    except Exception as e:
        import traceback
        error_msg = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)
        return error_msg.encode('utf-8'), 500, {"Content-Type": "text/plain"}
