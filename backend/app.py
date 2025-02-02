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





@njit
def calculate_forward_energy_fast(img_array):
    height, width, _ = img_array.shape
    energy_map = np.zeros((height, width))
    weights = np.array([0.299, 0.587, 0.114])

    for channel in range(3):
        grad_x = np.zeros((height, width), dtype=np.float32)
        grad_y = np.zeros((height, width), dtype=np.float32)

        grad_x[:, 1:] = np.abs(img_array[:, 1:, channel] - img_array[:, :-1, channel])
        grad_y[1:, :] = np.abs(img_array[1:, :, channel] - img_array[:-1, :, channel])

        energy_map += weights[channel] * (grad_x + grad_y)

    return energy_map

@njit
def find_vertical_seam_fast(energy_map):
    height, width = energy_map.shape
    dp = np.copy(energy_map)
    backtrack = np.zeros((height, width), dtype=np.int32)

    for i in range(1, height):
        for j in range(width):
            prev_cols = slice(max(0, j - 1), min(width, j + 2))
            min_idx = np.argmin(dp[i - 1, prev_cols])
            min_energy = dp[i - 1, prev_cols][min_idx]

            backtrack[i, j] = min_idx - (1 if j > 0 else 0)
            dp[i, j] += min_energy

    seam = np.zeros(height, dtype=np.int32)
    seam[-1] = np.argmin(dp[-1])

    for i in range(height - 2, -1, -1):
        offset = backtrack[i + 1, seam[i + 1]]
        seam[i] = min(max(seam[i + 1] + offset, 0), width - 1)

    return seam

@njit
def remove_seam_fast(img_array, seam):
    height, width, channels = img_array.shape
    new_array = np.zeros((height, width - 1, channels), dtype=img_array.dtype)

    for i in range(height):
        new_array[i, :seam[i]] = img_array[i, :seam[i]]
        new_array[i, seam[i]:] = img_array[i, seam[i] + 1:]

    return new_array

def update_energy_map(energy_map, seam):
    height, width = energy_map.shape
    new_energy_map = np.zeros((height, width - 1))

    for i in range(height):
        new_energy_map[i, :seam[i]] = energy_map[i, :seam[i]]
        new_energy_map[i, seam[i]:] = energy_map[i, seam[i] + 1:]

    return new_energy_map

def downscale_image(img_array, scale_factor):
    height, width, _ = img_array.shape
    new_height = int(height * scale_factor)
    new_width = int(width * scale_factor)
    resized_img = (resize(img_array, (new_height, new_width), anti_aliasing=True) * 255).astype(np.uint8)
    return resized_img

def post_process(img_array, start_progress):
    processed_img = np.zeros_like(img_array, dtype=np.uint8)
    total_channels = 3
    progress = start_progress

    for channel in range(total_channels):
        channel_data = img_array[:, :, channel].astype(np.float32) / 255.0
        processed_channel = restoration.denoise_bilateral(
            channel_data, sigma_color=0.05, sigma_spatial=5, channel_axis=None
        )
        processed_img[:, :, channel] = (processed_channel * 255).astype(np.uint8)

        progress = start_progress + ((channel + 1) / total_channels) * (100 - start_progress)
        socketio.emit('progress', {'progress': progress})
        socketio.sleep(0)

    return processed_img

def get_image_size(image_bytes):
    size_in_bytes = image_bytes.getbuffer().nbytes
    size_in_kb = size_in_bytes / 1024
    size_in_mb = size_in_kb / 1024

    if size_in_mb >= 1:
        return f"{size_in_mb:.2f} MB"
    return f"{size_in_kb:.2f} KB"

def compress_image(image_path, reduction_percentage):
    try:
        img = np.array(Image.open(image_path).convert('RGB'))
        original_height, original_width, _ = img.shape
        target_width = int(original_width * (1 - reduction_percentage / 100))
        
        max_seams = int(original_width * 0.03)
        num_seams = min(original_width - target_width, max_seams)
        
        remaining_width = original_width - num_seams
        scale_factor = target_width / remaining_width
        
        seam_removal_weight = 0.5
        downscaling_weight = 0.2
        post_processing_weight = 0.3

        progress = 0.0

        energy_map = calculate_forward_energy_fast(img)
        for i in range(num_seams):
            if img.shape[1] <= 2:
                break
                
            seam = find_vertical_seam_fast(energy_map)
            img = remove_seam_fast(img, seam)
            energy_map = update_energy_map(energy_map, seam)
            
            progress = ((i + 1) / num_seams) * seam_removal_weight * 100
            socketio.emit('progress', {'progress': progress})
            socketio.sleep(0)

        if scale_factor < 1.0:
            img = downscale_image(img, scale_factor)
            progress = (seam_removal_weight + downscaling_weight) * 100
            socketio.emit('progress', {'progress': progress})
            socketio.sleep(0)
        
        start_progress = (seam_removal_weight + downscaling_weight) * 100
        img = post_process(img, start_progress)
        progress = 100.0
        socketio.emit('progress', {'progress': progress})
        
        final_image = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        
        return final_image
    except Exception as e:
        print(f"Error in compress_image: {str(e)}")
        raise

@socketio.on('connect')
def handle_connect():
    emit('connected', {'data': 'Connected successfully'})

@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected from WebSocket")

@app.route('/compress', methods=['POST'])
def compress():
    try:
        if 'file' not in request.files or 'reduction_percentage' not in request.form:
            return jsonify({'error': 'Missing file or reduction_percentage'}), 400

        file = request.files['file']
        reduction_percentage = int(request.form['reduction_percentage'])

        if not (0 <= reduction_percentage <= 100):
            return jsonify({'error': 'reduction_percentage must be between 0 and 100'}), 400

        file_content = file.read()
        original_size = get_image_size(BytesIO(file_content))
        img = Image.open(BytesIO(file_content)).convert('RGB')

        MAX_RESOLUTION = 1024
        if img.width > MAX_RESOLUTION or img.height > MAX_RESOLUTION:
            img.thumbnail((MAX_RESOLUTION, MAX_RESOLUTION))

        img_array = np.array(img)

        original_height, original_width, _ = img_array.shape
        target_width = int(original_width * (1 - reduction_percentage / 100))
        aspect_ratio = original_height / original_width
        target_height = int(target_width * aspect_ratio)

        img_array = resize(img_array, (target_height, target_width), anti_aliasing=True)
        img_array = (img_array * 255).astype(np.uint8)

        compressed_image = Image.fromarray(img_array)

        img_io = BytesIO()
        compressed_image.save(img_io, 'JPEG', quality=85)
        img_io.seek(0)

        final_size = get_image_size(img_io)

        del img_array
        gc.collect()

        response = send_file(
            img_io,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name='compressed_image.jpg'
        )

        response.headers['final-width'] = str(compressed_image.width)
        response.headers['final-height'] = str(compressed_image.height)
        response.headers['original-size'] = original_size
        response.headers['final-size'] = final_size

        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=True, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)