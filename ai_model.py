"""
AI Model Handler
----------------
Loads the trained EfficientNetV2 X-ray model
and performs predictions.
"""

import tensorflow as tf
from tensorflow.keras.utils import load_img, img_to_array
import numpy as np
import os


MODEL_PATH = "xray_model.keras"

# Load model once when Flask starts
print("Loading AI model...")

try:
    model = tf.keras.models.load_model(MODEL_PATH)
    print("AI model loaded successfully!")

except Exception as e:
    print("MODEL LOAD ERROR:", e)
    model = None


def analyze_image(image_path):

    try:

        if model is None:
            return {
                "error": "Model not loaded"
            }


        if not os.path.exists(image_path):
            return {
                "error": "Image not found"
            }


        # Load image
        img = load_img(
            image_path,
            target_size=(224, 224)
        )


        # Convert image
        img_array = img_to_array(img)


        # Add batch dimension
        img_array = np.expand_dims(img_array, axis=0)


        # EfficientNetV2 preprocessing
        img_array = tf.keras.applications.efficientnet_v2.preprocess_input(
            img_array
        )


        # Prediction
        prediction = float(
            model.predict(img_array)[0][0]
        )


        print("RAW MODEL OUTPUT:", prediction)


        # Convert output into readable result
        if prediction >= 0.5:

            result = "Normal X-ray Pattern Suggested"
            confidence = prediction

        else:

            result = "Possible Pneumonia Pattern Detected"
            confidence = 1 - prediction


        return {
            "prediction": result,
            "confidence": round(confidence * 100, 2),
            "status": "ok"
        }


    except Exception as e:

        print("ANALYSIS ERROR:", e)

        return {
            "error": str(e)
        }