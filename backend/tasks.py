# backend/tasks.py

import redis
import json
from rq.job import Job
import os

# Import your scraper functions
from georgia_scraper import run_georgia_verification
from california_scraper import run_california_verification

def run_scraper_task(job_id, state, csv_data, api_key, mapping):
    """
    This is the main function that the RQ worker will execute.
    It runs the scraper and saves the logs and results to Redis.
    """
    # Connect to Redis
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    redis_conn = redis.from_url(redis_url)

    # Get the job instance
    job = Job.fetch(job_id, connection=redis_conn)
    job.meta['status'] = 'running'
    job.save_meta()
    
    # A helper function to append logs to Redis
    def log_to_redis(message):
        redis_conn.rpush(f"logs:{job_id}", message)

    try:
        # Choose the correct scraper function
        if state == 'georgia':
            scraper_generator = run_georgia_verification(csv_data, api_key, log_to_redis)
        elif state == 'california':
            scraper_generator = run_california_verification(csv_data, api_key, log_to_redis)
        else:
            raise ValueError("Invalid state provided")

        # The scraper now returns the final results directly
        final_results_df = scraper_generator
        
        # Save the final results to Redis
        job.meta['status'] = 'finished'
        job.meta['results'] = final_results_df.to_json(orient='records')
        job.save_meta()
        log_to_redis(f"\n--- [Module End] {state.capitalize()} verification complete. ---")

    except Exception as e:
        # If anything goes wrong, log the error and mark the job as failed
        error_message = f"!!! MODULE ERROR: An unexpected error occurred: {e} !!!"
        log_to_redis(error_message)
        job.meta['status'] = 'failed'
        job.meta['error'] = error_message
        job.save_meta()