import axios from "axios";
import fs from "fs";
import { io } from "socket.io-client";
import FormData from "form-data"; // Import the form-data library

const apiClient = axios.create({
    baseURL: "http://127.0.0.1:5000",
    headers: {
        "Content-Type": "multipart/form-data",
    },
    responseType: "arraybuffer", // Ensures response is treated as binary data
});

async function testCompressImage() {
    const formData = new FormData();

    // Load an image file (update with an actual image path on your system)
    const imageFile = fs.readFileSync("./big_test.jpg");
    formData.append("file", imageFile, "test-image.jpg");
    formData.append("reduction_percentage", "20");

    // Connect to the WebSocket server
    const socket = io("http://127.0.0.1:5000");

    // Log WebSocket connection status
    socket.on("connect", async () => {
        console.log("Connected to WebSocket server");

        try {
            // Make the HTTP request only after the WebSocket connection is established
            const response = await apiClient.post("/compress", formData, {
                headers: formData.getHeaders(), // Use getHeaders from the form-data library
            });

            // Convert response to a buffer and save as a file
            fs.writeFileSync("compressed.jpg", Buffer.from(response.data));
            console.log("Compression successful! Saved as compressed.jpg");

            // Log final image dimensions and sizes from headers
            console.log("Final image dimensions:", {
                width: response.headers["final-width"],
                height: response.headers["final-height"],
            });
            console.log("Original size:", response.headers["original-size"]);
            console.log("Final size:", response.headers["final-size"]);
        } catch (error) {
            console.error("Compression failed:", error.response?.data || error.message);
        } finally {
            // Disconnect the WebSocket after the test
            socket.disconnect();
        }
    });

    socket.on("disconnect", () => {
        console.log("Disconnected from WebSocket server");
    });

    socket.on("connect_error", (error) => {
        console.error("WebSocket connection error:", error);
    });

    // Listen for the 'progress' event
    socket.on("progress", (data) => {
        console.log(`Progress: ${data.progress.toFixed(2)}%`);
    });
}


async function runTests() {
    await testCompressImage();
}

runTests();