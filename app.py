from flask import Flask
from waitress import serve

app = Flask(__name__)


@app.get('/')
def index():
    return 'Hello World', 200, {'Content-Type': 'text/plain; charset=utf-8'}


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=8000)
