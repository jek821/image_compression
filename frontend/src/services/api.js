import axios from "axios";
import FormData from "form-data";

const apiClient = axios.create({
    baseURL: "https://dynamic-image-compression.onrender.com",
    headers: {
        "Content-Type": "multipart/form-data",
    },
    responseType: "arraybuffer", // Expect binary data as the response
});

export default {
    compressImage(file, reductionPercentage) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("reduction_percentage", reductionPercentage.toString());

        return apiClient.post("/compress", formData);

    },
};