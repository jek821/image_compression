from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_socketio import SocketIO, emit
import numpy as np
from numba import njit
from PIL import Image
from skimage.transform import resize
from skimage import restoration
import os
import time
from io import BytesIO
from flask_cors import CORS 
import gc
from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
import os

# app = Flask(__name__, static_folder="dist", static_url_path="/")

app = Flask(__name__)

# Allow all origins in development, restrict in production
CORS(
    app,
    resources={
        r"/*": {
            "origins": ["https://dynamic-image-compression.onrender.com", "http://192.168.243.36:3000", "http://localhost:3000"],  # Restrict to production frontend URL
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Accept"],
            "supports_credentials": True,
            "expose_headers": ["final-width", "final-height", "original-size", "final-size"],
        }
    }
)

# Configure SocketIO with CORS for both local and deployed environments
socketio = SocketIO(
    app,
    cors_allowed_origins=[
        "https://dynamic-image-compression.onrender.com", "http://192.168.243.36:3000", "http://localhost:3000",
    ],
    async_mode='gevent',  # Use 'gevent' for async support
)



def get_image_size(image_bytes):
    """Get the size of the image in KB or MB from a BytesIO object."""
    size_in_bytes = image_bytes.getbuffer().nbytes
    size_in_kb = size_in_bytes / 1024
    size_in_mb = size_in_kb / 1024
    return f"{size_in_mb:.2f} MB" if size_in_mb >= 1 else f"{size_in_kb:.2f} KB"

def stream_image(image):
    """Stream the image in small chunks to avoid high memory usage."""
    img_io = BytesIO()
    image.save(img_io, 'JPEG', quality=85)
    img_io.seek(0)
    yield img_io.read(8192)

def calculate_energy(img_array):
    """Compute energy map using gradient magnitude."""
    gray = np.dot(img_array[..., :3], [0.299, 0.587, 0.114])
    dx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    dy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    return dx + dy

def find_seam(energy_map):
    """Finds the lowest-energy seam using dynamic programming."""
    height, width = energy_map.shape
    dp = energy_map.copy()
    backtrack = np.zeros_like(dp, dtype=np.int32)
    
    for i in range(1, height):
        for j in range(width):
            left = dp[i-1, j-1] if j > 0 else float('inf')
            up = dp[i-1, j]
            right = dp[i-1, j+1] if j < width-1 else float('inf')
            
            min_idx = np.argmin([left, up, right]) - 1 + j
            dp[i, j] += dp[i-1, min_idx]
            backtrack[i, j] = min_idx
    
    seam = np.zeros(height, dtype=np.int32)
    seam[-1] = np.argmin(dp[-1])
    for i in range(height-2, -1, -1):
        seam[i] = backtrack[i+1, seam[i+1]]
    
    return seam

def remove_seam(img_array, seam):
    """Remove the specified seam from the image array."""
    height, width, channels = img_array.shape
    new_array = np.zeros((height, width-1, channels), dtype=img_array.dtype)
    for i in range(height):
        new_array[i, :seam[i]] = img_array[i, :seam[i]]
        new_array[i, seam[i]:] = img_array[i, seam[i]+1:]
    return new_array

@app.route('/compress', methods=['POST'])
def compress():
    try:
        if 'file' not in request.files or 'reduction_percentage' not in request.form:
            return jsonify({'error': 'Missing file or reduction_percentage'}), 400

        file = request.files['file']
        reduction_percentage = int(request.form['reduction_percentage'])
        
        if not (0 <= reduction_percentage <= 100):
            return jsonify({'error': 'Reduction percentage must be between 0 and 100'}), 400

        img = Image.open(file.stream)
        original_size = get_image_size(BytesIO(file.read()))
        img_array = np.array(img)

        original_width = img.width
        target_width = int(original_width * (1 - reduction_percentage / 100))
        
        total_steps = original_width - target_width
        for step in range(total_steps):
            energy_map = calculate_energy(img_array)
            seam = find_seam(energy_map)
            img_array = remove_seam(img_array, seam)
            progress = (step + 1) / total_steps * 100
            socketio.emit('progress', {'progress': progress})
            gc.collect()

        img = Image.fromarray(img_array)
        gc.collect()
        
        response = send_file(
            stream_image(img),
            mimetype='image/jpeg',
            as_attachment=True,
            download_name='compressed_image.jpg'
        )

        response.headers['final-width'] = str(img.width)
        response.headers['final-height'] = str(img.height)
        response.headers['original-size'] = original_size
        response.headers['final-size'] = get_image_size(BytesIO(file.read()))

        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    print("Client connected via WebSocket")
    emit('connected', {'data': 'Connected successfully'})

@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected from WebSocket")

if __name__ == "__main__":
    print("Starting Flask app with WebSocket support...")
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=True, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
