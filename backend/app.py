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

from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
import os

app = Flask(__name__, static_folder="dist", static_url_path="/")


# Allow all origins in development, restrict in production
if os.getenv("FLASK_ENV") == "development":
    CORS(
        app,
        resources={
            r"/*": {
                "origins": "*",  # Allow all origins in development
                "methods": ["GET", "POST", "OPTIONS"],
                "allow_headers": ["Content-Type", "Accept"],
                "supports_credentials": True,
                "expose_headers": ["final-width", "final-height", "original-size", "final-size"],
            }
        }
    )
else:
    CORS(
        app,
        resources={
            r"/*": {
                "origins": ["https://dynamic-image-compression.onrender.com"],  # Restrict to production frontend URL
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
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://dynamic-image-compression.onrender.com",
    ],
    async_mode='gevent',  # Use 'gevent' for async support
)



@app.route('/')
def serve_vue_app():
    """Serve the main Vue index.html"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static_files(path):
    """Serve other static files like JS, CSS, images"""
    return send_from_directory(app.static_folder, path)


# Optimized energy calculation using Numba
@njit
def calculate_forward_energy_fast(img_array):
    """Calculate forward energy using Numba for speed."""
    print("Calculating forward energy...")
    height, width, _ = img_array.shape
    energy_map = np.zeros((height, width))
    weights = np.array([0.299, 0.587, 0.114])

    for channel in range(3):
        grad_x = np.zeros((height, width), dtype=np.float32)
        grad_y = np.zeros((height, width), dtype=np.float32)

        # Compute gradients
        grad_x[:, 1:] = np.abs(img_array[:, 1:, channel] - img_array[:, :-1, channel])
        grad_y[1:, :] = np.abs(img_array[1:, :, channel] - img_array[:-1, :, channel])

        # Combine gradients with weights
        energy_map += weights[channel] * (grad_x + grad_y)

    print("Forward energy calculation complete.")
    return energy_map

# Optimized seam finding using Numba
@njit
def find_vertical_seam_fast(energy_map):
    """Find vertical seam using dynamic programming and Numba."""
    print("Finding vertical seam...")
    height, width = energy_map.shape
    dp = np.copy(energy_map)
    backtrack = np.zeros((height, width), dtype=np.int32)

    # Fill DP table
    for i in range(1, height):
        for j in range(width):
            prev_cols = slice(max(0, j - 1), min(width, j + 2))
            min_idx = np.argmin(dp[i - 1, prev_cols])
            min_energy = dp[i - 1, prev_cols][min_idx]

            # Store the relative offset (-1, 0, or 1) in backtrack
            backtrack[i, j] = min_idx - (1 if j > 0 else 0)
            dp[i, j] += min_energy

    # Backtrack to find optimal seam
    seam = np.zeros(height, dtype=np.int32)
    seam[-1] = np.argmin(dp[-1])

    for i in range(height - 2, -1, -1):
        offset = backtrack[i + 1, seam[i + 1]]
        seam[i] = min(max(seam[i + 1] + offset, 0), width - 1)

    print("Vertical seam found.")
    return seam

# Optimized seam removal using Numba
@njit
def remove_seam_fast(img_array, seam):
    """Remove vertical seam using Numba for speed."""
    print("Removing vertical seam...")
    height, width, channels = img_array.shape
    new_array = np.zeros((height, width - 1, channels), dtype=img_array.dtype)

    for i in range(height):
        new_array[i, :seam[i]] = img_array[i, :seam[i]]
        new_array[i, seam[i]:] = img_array[i, seam[i] + 1:]

    print("Vertical seam removed.")
    return new_array

def update_energy_map(energy_map, seam):
    """Update the energy map after removing a seam."""
    print("Updating energy map...")
    height, width = energy_map.shape
    new_energy_map = np.zeros((height, width - 1))

    for i in range(height):
        new_energy_map[i, :seam[i]] = energy_map[i, :seam[i]]
        new_energy_map[i, seam[i]:] = energy_map[i, seam[i] + 1:]

    print("Energy map updated.")
    return new_energy_map

def downscale_image(img_array, scale_factor):
    """Downscale the image by a given factor while preserving data type."""
    print(f"Downscaling image with scale factor: {scale_factor}...")
    height, width, _ = img_array.shape
    new_height = int(height * scale_factor)
    new_width = int(width * scale_factor)
    resized_img = (resize(img_array, (new_height, new_width), anti_aliasing=True) * 255).astype(np.uint8)
    print("Image downscaling complete.")
    return resized_img

def post_process(img_array, start_progress):
    """Apply post-processing to reduce artifacts and update progress incrementally."""
    print("Applying post-processing...")
    processed_img = np.zeros_like(img_array, dtype=np.uint8)
    total_channels = 3  # RGB channels
    progress = start_progress

    for channel in range(total_channels):
        print(f"Processing channel {channel + 1}/{total_channels}...")
        channel_data = img_array[:, :, channel].astype(np.float32) / 255.0
        processed_channel = restoration.denoise_bilateral(
            channel_data, sigma_color=0.05, sigma_spatial=5, channel_axis=None
        )
        processed_img[:, :, channel] = (processed_channel * 255).astype(np.uint8)

        # Update progress for each channel
        progress = start_progress + ((channel + 1) / total_channels) * (100 - start_progress)
        print(f"Post-processing progress: {progress:.2f}%")
        socketio.emit('progress', {'progress': progress})
        socketio.sleep(0)  # Allow other threads to process

    print("Post-processing complete.")
    return processed_img
    
def get_image_size(image_bytes):
    """Get the size of the image in KB or MB from a BytesIO object."""
    print("Calculating image size...")
    
    # Get the size in bytes
    size_in_bytes = image_bytes.getbuffer().nbytes
    
    # Convert to KB and MB
    size_in_kb = size_in_bytes / 1024
    size_in_mb = size_in_kb / 1024
    
    # Format the size
    if size_in_mb >= 1:
        return f"{size_in_mb:.2f} MB"
    return f"{size_in_kb:.2f} KB"

def track_progress(current_step, total_steps):
    """Track the percentage completion of the compression process."""
    if total_steps == 0:
        return 100.0
    progress = (current_step / total_steps) * 100
    print(f"Progress: {progress:.2f}%")
    return progress

def compress_image(image_path, reduction_percentage):
    """Compress an image using seam carving and downscaling based on the given reduction percentage."""
    try:
        print(f"Starting image compression for {image_path} with {reduction_percentage}% reduction...")
        img = np.array(Image.open(image_path).convert('RGB'))
        original_height, original_width, _ = img.shape
        target_width = int(original_width * (1 - reduction_percentage / 100))
        
        # Limit seam removal to 3% of the original width
        max_seams = int(original_width * 0.03)
        num_seams = min(original_width - target_width, max_seams)
        
        # Calculate downscale factor
        remaining_width = original_width - num_seams
        scale_factor = target_width / remaining_width
        
        # Define weights for progress tracking
        seam_removal_weight = 0.5  # 50% of progress
        downscaling_weight = 0.2   # 20% of progress
        post_processing_weight = 0.3  # 30% of progress

        # Initialize progress
        progress = 0.0

        # Remove vertical seams
        energy_map = calculate_forward_energy_fast(img)
        for i in range(num_seams):
            if img.shape[1] <= 2:
                print("Image width too small to remove more seams.")
                break
                
            seam = find_vertical_seam_fast(energy_map)
            img = remove_seam_fast(img, seam)
            energy_map = update_energy_map(energy_map, seam)
            
            # Update progress for seam removal
            progress = ((i + 1) / num_seams) * seam_removal_weight * 100
            print(f"Progress after seam removal {i + 1}/{num_seams}: {progress:.2f}%")
            socketio.emit('progress', {'progress': progress})
            socketio.sleep(0)  # Allow other threads to process

        # Downscale if necessary
        if scale_factor < 1.0:
            print(f"Downscaling image with scale factor: {scale_factor}...")
            img = downscale_image(img, scale_factor)
            # Update progress for downscaling
            progress = (seam_removal_weight + downscaling_weight) * 100
            print(f"Progress after downscaling: {progress:.2f}%")
            socketio.emit('progress', {'progress': progress})
            socketio.sleep(0)
        
        # Post-process with incremental progress updates
        print("Applying post-processing...")
        start_progress = (seam_removal_weight + downscaling_weight) * 100
        img = post_process(img, start_progress)
        # Final progress update
        progress = 100.0
        print(f"Progress after post-processing: {progress:.2f}%")
        socketio.emit('progress', {'progress': progress})
        
        final_image = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        
        return final_image
    except Exception as e:
        print(f"Error in compress_image: {str(e)}")
        raise

@socketio.on('connect')
def handle_connect():
    print("Client connected via WebSocket")
    emit('connected', {'data': 'Connected successfully'})

@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected from WebSocket")

@app.route('/compress', methods=['POST'])
def compress():
    try:
        print("Received compression request")
        if 'file' not in request.files:
            print("No file provided")
            return jsonify({'error': 'No file provided'}), 400
        
        if 'reduction_percentage' not in request.form:
            print("No reduction_percentage provided")
            return jsonify({'error': 'No reduction_percentage provided'}), 400

        file = request.files['file']
        reduction_percentage = int(request.form['reduction_percentage'])

        if not (0 <= reduction_percentage <= 100):
            print("Invalid reduction_percentage")
            return jsonify({'error': 'reduction_percentage must be between 0 and 100'}), 400

        # Read the file content once and store it in a variable
        file_content = file.read()

        # Save temporary file
        temp_path = "temp_uploaded_image.jpg"
        with open(temp_path, "wb") as temp_file:
            temp_file.write(file_content)

        # Compress image
        compressed_image = compress_image(temp_path, reduction_percentage)

        # Prepare response
        img_io = BytesIO()
        compressed_image.save(img_io, 'JPEG', quality=85)
        img_io.seek(0)

        # Calculate sizes
        original_size = get_image_size(BytesIO(file_content))  # Use the stored file content
        final_size = get_image_size(img_io)

        # Cleanup
        os.remove(temp_path)

        # Prepare response with sizes
        response = send_file(
            img_io,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name='compressed_image.jpg'
        )

        # Set headers for final image dimensions and sizes
        response.headers['final-width'] = str(compressed_image.width)
        response.headers['final-height'] = str(compressed_image.height)
        response.headers['original-size'] = original_size
        response.headers['final-size'] = final_size

        return response

    except Exception as e:
        print(f"Error in compress endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    print("Starting Flask app with WebSocket support...")
    socketio.run(app, debug=True, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)