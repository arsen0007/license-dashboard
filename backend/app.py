# backend/app.py

import os
import uuid
from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import io
import json
import redis
from rq import Queue

# Import the task function
from tasks import run_scraper_task

# Setup Flask App and Redis/RQ connection
app = Flask(__name__)
CORS(app)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_conn = redis.from_url(redis_url)
q = Queue(connection=redis_conn)

@app.route('/start-scraping', methods=['POST'])
def start_scraping():
    """
    This endpoint takes the user's request, creates a job,
    and adds it to the Redis queue. It returns a job ID instantly.
    """
    if 'file' not in request.files: return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No selected file"}), 400

    api_key = request.form.get('apiKey')
    state = request.form.get('state')
    mapping_json = request.form.get('mapping')

    if not all([api_key, state, mapping_json]):
        return jsonify({"error": "API key, state, or mapping is missing"}), 400

    try:
        column_mapping = json.loads(mapping_json)
        csv_data = pd.read_csv(file.stream.read().decode("UTF8"))
        
        # Rename columns based on user's mapping before passing to the task
        rename_map = {v: k for k, v in column_mapping.items()}
        csv_data.rename(columns=rename_map, inplace=True)

        # Enqueue the job. The worker will pick this up.
        # We pass the dataframe as a JSON string to make it queue-safe.
        job = q.enqueue(
            run_scraper_task,
            job_id=str(uuid.uuid4()), # Create a unique ID for this job
            args=(state, csv_data.to_json(orient='records'), api_key, column_mapping),
            job_timeout='2h' # Allow the job to run for up to 2 hours
        )
        
        return jsonify({"job_id": job.id}), 202 # 202 Accepted

    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    """
    This endpoint is polled by the frontend to get live updates
    on the job's status, logs, and results.
    """
    job = q.fetch_job(job_id)
    if job:
        logs = [log.decode('utf-8') for log in redis_conn.lrange(f"logs:{job_id}", 0, -1)]
        response_object = {
            "id": job.id,
            "status": job.get_status(),
            "meta": job.meta,
            "logs": logs
        }
        return jsonify(response_object), 200
    else:
        return jsonify({"error": "Job not found"}), 404