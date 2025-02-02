from flask import Flask, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import numpy as np
from numba import njit
from PIL import Image
import os
import tempfile
from io import BytesIO
import gc
import shutil

app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": ["https://dynamic-image-compression.onrender.com", "http://192.168.243.36:3000", "http://localhost:3000"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Accept"],
        "supports_credentials": True,
        "expose_headers": ["final-width", "final-height", "original-size", "final-size"],
    }
})

socketio = SocketIO(
    app,
    cors_allowed_origins=[
        "https://dynamic-image-compression.onrender.com",
        "http://192.168.243.36:3000",
        "http://localhost:3000",
    ],
    async_mode='gevent'
)

# Progress weight constants
ENERGY_CALCULATION_WEIGHT = 0.3
SEAM_FINDING_WEIGHT = 0.4
SEAM_REMOVAL_WEIGHT = 0.3

def emit_progress(stage, current, total, base_progress=0):
    """Emit progress updates with stage information"""
    if total == 0:
        return
    
    stage_weights = {
        'energy_calculation': ENERGY_CALCULATION_WEIGHT,
        'seam_finding': SEAM_FINDING_WEIGHT,
        'seam_removal': SEAM_REMOVAL_WEIGHT
    }
    
    stage_weight = stage_weights.get(stage, 1.0)
    progress = base_progress + (current / total * stage_weight * 100)
    
    socketio.emit('progress', {
        'progress': min(progress, 100),
        'stage': stage,
        'detail': f"Processing {stage.replace('_', ' ')} ({current}/{total})"
    })
    socketio.sleep(0)  # Allow other threads to process

@njit
def calculate_energy_chunk(img_chunk):
    """Calculate energy for a chunk of the image."""
    height, width, _ = img_chunk.shape
    energy = np.zeros((height, width), dtype=np.float32)
    
    for y in range(height):
        for x in range(width):
            dx = np.zeros(3)
            dy = np.zeros(3)
            
            if x > 0 and x < width - 1:
                dx = img_chunk[y, x + 1] - img_chunk[y, x - 1]
            elif x > 0:
                dx = img_chunk[y, x] - img_chunk[y, x - 1]
            else:
                dx = img_chunk[y, x + 1] - img_chunk[y, x]
                
            if y > 0 and y < height - 1:
                dy = img_chunk[y + 1, x] - img_chunk[y - 1, x]
            elif y > 0:
                dy = img_chunk[y, x] - img_chunk[y - 1, x]
            else:
                dy = img_chunk[y + 1, x] - img_chunk[y, x]
                
            energy[y, x] = np.sqrt(np.sum(dx**2) + np.sum(dy**2))
    
    return energy

@njit
def find_seam_chunk(energy_chunk, dp_chunk, backtrack_chunk):
    """Find seam in a chunk using dynamic programming."""
    height, width = energy_chunk.shape
    
    dp_chunk[0] = energy_chunk[0]
    for y in range(1, height):
        for x in range(width):
            left = dp_chunk[y-1, x-1] if x > 0 else float('inf')
            middle = dp_chunk[y-1, x]
            right = dp_chunk[y-1, x+1] if x < width-1 else float('inf')
            
            min_energy = min(left, middle, right)
            dp_chunk[y, x] = energy_chunk[y, x] + min_energy
            
            if min_energy == middle:
                backtrack_chunk[y, x] = 0
            elif min_energy == left:
                backtrack_chunk[y, x] = -1
            else:
                backtrack_chunk[y, x] = 1
    
    return dp_chunk, backtrack_chunk

def process_image_with_mmap(image_path, reduction_percentage, temp_dir):
    """Process image using memory-mapped arrays with detailed progress tracking."""
    img = Image.open(image_path).convert('RGB')
    img_array = np.array(img)
    height, width, _ = img_array.shape
    
    seams_to_remove = int(width * reduction_percentage / 100)
    chunk_size = 500  # Process 500 rows at a time
    
    # Create memory-mapped files
    energy_map = np.memmap(os.path.join(temp_dir, 'energy_map.npy'), 
                          dtype=np.float32, mode='w+', shape=(height, width))
    dp = np.memmap(os.path.join(temp_dir, 'dp.npy'), 
                   dtype=np.float32, mode='w+', shape=(height, width))
    backtrack = np.memmap(os.path.join(temp_dir, 'backtrack.npy'), 
                         dtype=np.int8, mode='w+', shape=(height, width))
    
    total_chunks = height // chunk_size + (1 if height % chunk_size else 0)
    
    for seam_idx in range(seams_to_remove):
        if width <= 2:
            break
            
        # Calculate energy in chunks with progress tracking
        for chunk_idx, i in enumerate(range(0, height, chunk_size)):
            chunk_end = min(i + chunk_size, height)
            img_chunk = img_array[i:chunk_end]
            energy_map[i:chunk_end] = calculate_energy_chunk(img_chunk)
            
            # Emit progress for energy calculation
            base_progress = (seam_idx / seams_to_remove) * 100
            emit_progress('energy_calculation', chunk_idx + 1, total_chunks, base_progress)
        
        # Find seam using chunked dynamic programming
        dp[:] = float('inf')
        backtrack[:] = 0
        for chunk_idx, i in enumerate(range(0, height, chunk_size)):
            chunk_end = min(i + chunk_size, height)
            dp[i:chunk_end], backtrack[i:chunk_end] = find_seam_chunk(
                energy_map[i:chunk_end], dp[i:chunk_end], backtrack[i:chunk_end]
            )
            
            # Emit progress for seam finding
            emit_progress('seam_finding', chunk_idx + 1, total_chunks, base_progress)
        
        # Find and remove seam
        seam = np.zeros(height, dtype=np.int32)
        seam[-1] = np.argmin(dp[-1])
        for y in range(height-2, -1, -1):
            offset = backtrack[y+1, seam[y+1]]
            seam[y] = seam[y+1] + offset
        
        # Remove seam with progress tracking
        new_img_array = np.zeros((height, width-1, 3), dtype=np.uint8)
        for y in range(height):
            new_img_array[y, :seam[y]] = img_array[y, :seam[y]]
            new_img_array[y, seam[y]:] = img_array[y, seam[y]+1:]
            if y % chunk_size == 0:
                emit_progress('seam_removal', y, height, base_progress)
        
        img_array = new_img_array
        width -= 1
        
        # Force sync and cleanup
        energy_map.flush()
        dp.flush()
        backtrack.flush()
        gc.collect()
    
    # Clean up memory-mapped files
    del energy_map
    del dp
    del backtrack
    gc.collect()
    
    return Image.fromarray(img_array)

def get_image_size(image_bytes):
    size_in_bytes = image_bytes.getbuffer().nbytes
    size_in_kb = size_in_bytes / 1024
    size_in_mb = size_in_kb / 1024
    return f"{size_in_mb:.2f} MB" if size_in_mb >= 1 else f"{size_in_kb:.2f} KB"

@socketio.on('connect')
def handle_connect():
    print("Client connected via WebSocket")
    emit('connected', {'data': 'Connected successfully'})

@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected from WebSocket")

@app.route('/compress', methods=['POST'])
def compress():
    temp_dir = None
    try:
        if 'file' not in request.files or 'reduction_percentage' not in request.form:
            return jsonify({'error': 'Missing file or reduction_percentage'}), 400

        file = request.files['file']
        reduction_percentage = int(request.form['reduction_percentage'])

        if not (0 <= reduction_percentage <= 100):
            return jsonify({'error': 'reduction_percentage must be between 0 and 100'}), 400

        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        
        # Save uploaded file
        temp_image_path = os.path.join(temp_dir, 'input_image.jpg')
        file.save(temp_image_path)
        
        # Calculate original size
        with open(temp_image_path, 'rb') as f:
            original_size = get_image_size(BytesIO(f.read()))

        # Process image
        compressed_image = process_image_with_mmap(temp_image_path, reduction_percentage, temp_dir)
        
        # Save result
        output = BytesIO()
        compressed_image.save(output, format='JPEG', quality=85, optimize=True)
        output.seek(0)
        
        final_size = get_image_size(output)

        # Prepare response
        response = send_file(
            output,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name='compressed_image.jpg'
        )

        response.headers.update({
            'final-width': str(compressed_image.width),
            'final-height': str(compressed_image.height),
            'original-size': original_size,
            'final-size': final_size
        })

        return response

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500
        
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        gc.collect()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host="0.0.0.0", port=port)