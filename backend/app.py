# backend/app.py

import os
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import pandas as pd
import io
import json # Import the json library

# Import your scraper functions and shared state
from georgia_scraper import run_georgia_verification
from california_scraper import run_california_verification
import shared_state

app = Flask(__name__)
CORS(app)

@app.route('/stop', methods=['POST'])
def stop_verification():
    shared_state.STOP_REQUESTED = True
    return jsonify({"message": "Stop signal received"}), 200

@app.route('/run-verification', methods=['POST'])
def run_verification_endpoint():
    shared_state.STOP_REQUESTED = False

    if 'file' not in request.files: return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No selected file"}), 400

    api_key = request.form.get('apiKey')
    state = request.form.get('state')
    # --- NEW: Get the column mapping from the request ---
    mapping_json = request.form.get('mapping')

    if not all([api_key, state, mapping_json]):
        return jsonify({"error": "API key, state, or mapping is missing"}), 400

    try:
        # --- NEW: Load the mapping from the JSON string ---
        column_mapping = json.loads(mapping_json)

        csv_data = io.StringIO(file.stream.read().decode("UTF8"))
        df = pd.read_csv(csv_data)
        
        # --- THE CORE FIX: Rename columns based on user's mapping ---
        # Create a reverse map for renaming: {'Fname': 'first name', 'Lname': 'last name'}
        rename_map = {v: k for k, v in column_mapping.items()}
        df.rename(columns=rename_map, inplace=True)
        # --- END FIX ---

        # Now the rest of the script works because the columns are correctly named!
        if state == 'georgia':
            scraper_generator = run_georgia_verification(df, api_key)
        elif state == 'california':
            scraper_generator = run_california_verification(df, api_key)
        else:
            return jsonify({"error": "Invalid state selected"}), 400

        return Response(scraper_generator, mimetype='text/plain')

    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)