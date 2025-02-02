<template>
  <div class="container">
    <!-- Header -->
    <header class="header">
      <h1>Image Compression by Seam Carving</h1>
    </header>

     <div class="main">
        <!-- Upload Section -->
        <div class="upload-section card">
          <h2>Upload an Image</h2>
          <div class="upload-box">
            <input type="file" @change="handleFileUpload" accept="image/*" id="file-input" />
            <label for="file-input">
              Choose a file or drag it here
            </label>
          </div>

        <div>
          <p v-if="isMobile" class="mobile-warning">
            For the best experience, please upload images from your camera roll instead of taking a new photo.
          </p>
        </div>

        </div>

        <!-- Dimensions Section -->
        <div v-if="imageUploaded" class="dimensions-section card">
          <h2>File Information</h2>
          <div class="dimensions-grid">
            <div class="dimension-item">
              <span class="dimension-label">Original Size:</span>
              <span class="dimension-value">{{ originalWidth }}x{{ originalHeight }}</span>
            </div>
            <div class="dimension-item">
              <span class="dimension-label">Processed Size:</span>
              <span class="dimension-value">{{ compressedWidth }}x{{ compressedHeight }}</span>
            </div>
            <div class="dimension-item">
              <span class="dimension-label">Original File Size:</span>
              <span class="dimension-value">{{ originalSize }}</span>
            </div>
            <div class="dimension-item">
              <span class="dimension-label">Compressed File Size:</span>
              <span class="dimension-value">{{ compressedSize }}</span>
            </div>
          </div>
        </div>

        <!-- Slider Section -->
        <div v-if="imageUploaded" class="slider-section card">
          <h2>Processing Control</h2>
          <div class="slider-container">
            <label for="compression-slider">Processing Level: {{ compressionPercentage }}%</label>
            <input
              type="range"
              id="compression-slider"
              v-model="compressionPercentage"
              min="0"
              max="100"
              @input="updateCompressedDimensions"
              :disabled="loading"
            />
          </div>
          <!-- Compression Button -->
          <button class="compress-button" @click="handleCompressImage" :disabled="loading">
            {{ loading ? "Compressing..." : "Compress Image" }}
          </button>
          <!-- Progress Bar -->
          <div v-if="loading" class="progress-bar-container">
            <div class="progress-bar" :style="{ width: progress + '%' }"></div>
          </div>
          <div v-if="showResizeWarning" class="warning-message">
            ⚠️ Your image must be automatically resized to a 1024 pixels at most to reduce memory usage. This helps us manage hosting costs and ensure smooth processing.
          </div>
        </div>

        <!-- Result Section -->
        <div v-if="compressedImageUrl" class="result-section card">
          <h2>Compressed Image</h2>
          <img :src="compressedImageUrl" alt="Compressed Image" class="compressed-image" />
          <button class="download-button" @click="downloadCompressedImage" :disabled="loading">
            Download Compressed Image
          </button>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="content">
      <!-- Main explanation section -->
      <div class="explanation">
          <h2>Dynamic Programming: A Systematic Approach to Optimization</h2>
          <div class="info-section">
          <h3>Core Concepts</h3>
          <p>
            Dynamic programming (DP) is a powerful algorithmic technique that optimizes complex problems by breaking them down into simpler subproblems. It's particularly effective when:
          </p>
          <ul class="concept-list">
            <li>The problem can be divided into <strong>overlapping subproblems</strong>.</li>
            <li>Solutions to these subproblems can be <strong>stored and reused</strong>.</li>
            <li>There exists an <strong>optimal substructure</strong>, where the optimal solution contains optimal solutions to its subproblems.</li>
          </ul>
        </div>

        <div class="info-section">
          <h3>From Recursion to Efficiency</h3>
          <p>
            Many recursive problems suffer from exponential time complexity, making them impractical for larger inputs. Dynamic programming transforms these inefficient recursive solutions into optimized algorithms through systematic storage and reuse of intermediate results.
          </p>
          <p>
            This approach typically reduces the time complexity from <strong>exponential</strong> to <strong>polynomial</strong>, making it feasible for real-world applications.
          </p>
        </div>

        <div class="info-section">
          <h3>The Power of Memoization</h3>
          <p>
            At its core, dynamic programming employs <strong>memoization</strong>—storing the results of expensive function calls and returning the cached result when the same inputs occur again. This technique prevents redundant calculations and dramatically improves performance.
          </p>
          <p>
            The <strong>DP matrix</strong> serves as a structured way to store these intermediate results, enabling efficient solution construction.
          </p>
        </div>

        <div class="info-section">
          <h3>Problem-Solving Framework</h3>
          <p>
            To apply dynamic programming effectively, follow this structured approach:
          </p>
          <ol class="framework-list">
            <li><strong>Identify</strong> if the problem has overlapping subproblems.</li>
            <li><strong>Define</strong> the state (what information we need to solve the subproblem).</li>
            <li><strong>Formulate</strong> the recurrence relation between states.</li>
            <li><strong>Determine</strong> the base cases.</li>
            <li><strong>Decide</strong> the order of computation (bottom-up or top-down).</li>
          </ol>
        </div>
        </div>  
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from "vue";
import { io } from "socket.io-client";
import apiService from "../services/api"; // Adjust the path as needed

// Reactive state
const imageUploaded = ref(false);
const originalWidth = ref(0);
const originalHeight = ref(0);
const compressedWidth = ref(0);
const compressedHeight = ref(0);
const compressionPercentage = ref(100);
const imageFile = ref(null);
const compressedImageUrl = ref(null);
const loading = ref(false);
const progress = ref(0);
const socket = ref(null);
const originalSize = ref(null);
const compressedSize = ref(null);
const showResizeWarning = ref(false);

// Maximum allowed dimensions for the compressed image
const MAX_WIDTH = 800; // Adjust as needed
const MAX_HEIGHT = 800; // Adjust as needed

// Initialize WebSocket connection
onMounted(() => {
  socket.value = io("https://dynamic-image-compression.onrender.com"); // Connect to the WebSocket server

  socket.value.on("progress", (data) => {
    progress.value = data.progress; // Update progress
  });
});

// Clean up WebSocket connection
onUnmounted(() => {
  if (socket.value) {
    socket.value.disconnect();
  }
});

const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

const handleFileUpload = (event) => {
  const file = event.target.files[0];
  if (!file) return;

  // Use the original file without EXIF or canvas manipulation
  imageFile.value = file;

  const img = new Image();
  img.src = URL.createObjectURL(file);

  img.onload = () => {
    originalWidth.value = img.width;
    originalHeight.value = img.height;
    imageUploaded.value = true;
    originalSize.value = 0;
    compressedSize.value = 0;
    updateCompressedDimensions();
  };

  img.onerror = (error) => {
    console.error('Failed to load image:', error); // Debugging
  };
};

// Update dimensions when compression percentage changes
const updateCompressedDimensions = () => {
  const scaleFactor = compressionPercentage.value / 100;

  // Calculate new dimensions based on the scale factor
  let newWidth = Math.round(originalWidth.value * scaleFactor);
  let newHeight = Math.round(originalHeight.value * scaleFactor);

  // Cap dimensions to the maximum resolution
  const maxResolution = 1024; // Match this with your backend's MAX_RESOLUTION
  if (newWidth > maxResolution || newHeight > maxResolution) {
    showResizeWarning.value = true;
    const aspectRatio = originalWidth.value / originalHeight.value;
    if (newWidth > newHeight) {
      newWidth = maxResolution;
      newHeight = Math.round(maxResolution / aspectRatio);
    } else {
      newHeight = maxResolution;
      newWidth = Math.round(maxResolution * aspectRatio);
    }
  }

  // Update the compressed dimensions
  compressedWidth.value = newWidth;
  compressedHeight.value = newHeight;
};

// Watch for compression percentage changes
watch(compressionPercentage, updateCompressedDimensions);

// Compress image using the API
const handleCompressImage = async () => {
  if (!imageFile.value || loading.value) return;

  loading.value = true;
  progress.value = 0;
  originalSize.value = null;
  compressedSize.value = null;

  try {
    const backendCompressionValue = 100 - compressionPercentage.value;
    const response = await apiService.compressImage(imageFile.value, backendCompressionValue);

    // Create a Blob from the response
    const blob = new Blob([response.data], { type: imageFile.value.type });
    const url = URL.createObjectURL(blob);
    compressedImageUrl.value = url;

    // Access headers safely
    const headers = response.headers;
    console.log("Response Headers:", headers);

    // Update dimensions and sizes
    compressedWidth.value = headers.get("final-width") || headers["final-width"];
    compressedHeight.value = headers.get("final-height") || headers["final-height"];
    originalSize.value = headers.get("original-size") || headers["original-size"];
    compressedSize.value = headers.get("final-size") || headers["final-size"];

  } catch (error) {
    console.error("Error compressing image:", error.response?.data || error.message);
  } finally {
    loading.value = false;
  }
};

const downloadCompressedImage = () => {
  if (!compressedImageUrl.value) return;

  // Create a temporary anchor element
  const link = document.createElement("a");
  link.href = compressedImageUrl.value;
  link.download = "compressed_image.jpg"; // Set the download filename
  document.body.appendChild(link); // Append to the DOM (required for Firefox)
  link.click(); // Trigger the download
  document.body.removeChild(link); // Clean up
};

</script>

<style scoped>
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background-color: #f4f4f9;
  margin: 0;
  padding: 0;
  color: #1a1a1a;
}

.container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem;
}

.header {
  text-align: center;
  padding: 2rem;
  background: linear-gradient(135deg, #6200ea, #7c4dff);
  color: white;
  border-radius: 12px;
  margin-bottom: 2rem;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.header h1 {
  margin: 0;
  font-size: 2.5rem;
  font-weight: 700;
}

.content {
  display: grid;
  grid-template-columns: 3fr 1fr;
  gap: 2rem;
}

.explanation {
  background-color: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  padding: 2rem;
}

.compressed-image {
  max-width: 100%;
  max-height: 400px; 
  object-fit: contain;
}

.explanation h2 {
  color: #6200ea;
  font-size: 1.75rem;
  margin-bottom: 1.5rem;
  font-weight: 700;
}

.info-section {
  margin-bottom: 2rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid #e0e0e0;
}

.info-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.info-section h3 {
  color: #4a4a4a;
  font-size: 1.25rem;
  margin-bottom: 1rem;
  font-weight: 600;
}

.info-section p {
  line-height: 1.7;
  color: #666;
  margin-bottom: 1rem;
}

.concept-list, .framework-list {
  margin-left: 1.5rem;
  margin-bottom: 1rem;
}

.concept-list li, .framework-list li {
  margin-bottom: 0.5rem;
  line-height: 1.6;
  color: #666;
}

.main {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.card {
  background-color: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.card h2 {
  color: #6200ea;
  font-size: 1.5rem;
  margin-bottom: 1.5rem;
  font-weight: 600;
}

.upload-box {
  border: 2px dashed #6200ea;
  border-radius: 12px;
  padding: 2rem;
  text-align: center;
  background-color: #f8f9fe;
  transition: all 0.3s ease;
}

.upload-box:hover {
  background-color: #f4f0ff;
  border-color: #7c4dff;
}

.upload-box input[type="file"] {
  display: none;
}

.upload-box label {
  cursor: pointer;
  color: #6200ea;
  font-size: 1.1rem;
  font-weight: 500;
}

.dimensions-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1rem;
}

.dimension-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.dimension-label {
  color: #666;
  font-size: 0.9rem;
  font-weight: 500;
}

.dimension-value {
  color: #1a1a1a;
  font-size: 1.25rem;
  font-weight: 600;
}

.slider-container {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.slider-container label {
  color: #4a4a4a;
  font-size: 1.1rem;
  font-weight: 500;
}

.slider-container input[type="range"] {
  width: 100%;
  height: 6px;
  background: #e0e0e0;
  border-radius: 3px;
  appearance: none;
  outline: none;
}

.slider-container input[type="range"]::-webkit-slider-thumb {
  appearance: none;
  width: 20px;
  height: 20px;
  background: #6200ea;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s ease;
}

.slider-container input[type="range"]::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.warning-message {
  margin-top: 1rem;
  padding: 0.75rem;
  background-color: #fff3cd; /* Light yellow background */
  border: 1px solid #ffeeba; /* Yellow border */
  border-radius: 8px;
  color: #856404; /* Dark yellow text */
  font-size: 0.9rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.compress-button {
  background-color: #6200ea;
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.3s ease;
  margin-top: 1rem;
}

.compress-button:hover {
  background-color: #7c4dff;
}

.compress-button:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.download-button {
  background-color: #4caf50;
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.3s ease;
  margin-top: 1rem;
}

.download-button:hover {
  background-color: #66bb6a;
}

.download-button:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.progress-bar-container {
  width: 100%;
  height: 10px;
  background-color: #e0e0e0;
  border-radius: 5px;
  margin-top: 1rem;
  overflow: hidden;
}


.mobile-warning {
  color: red;
  font-weight: bold;
  margin-top: 10px;
}


.progress-bar {
  height: 100%;
  background-color: #6200ea;
  border-radius: 5px;
  transition: width 0.3s ease;
}

@keyframes spin {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

@media (max-width: 1024px) {
  .content {
    grid-template-columns: 1fr;
  }
  
  .container {
    padding: 1rem;
  }
  
  .header {
    padding: 1.5rem;
  }
  
  .header h1 {
    font-size: 2rem;
  }
}

@media (max-width: 640px) {
  .dimensions-grid {
    grid-template-columns: 1fr;
  }
}
</style>