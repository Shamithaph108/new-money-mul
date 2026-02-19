from app import app

# The WSGI server (gunicorn, waitress, etc.) will import `app` from
# this module. Keep `app` exposed at module level.

if __name__ == "__main__":
    # Fallback for local development
    app.run(debug=False, host="0.0.0.0", port=5000)
