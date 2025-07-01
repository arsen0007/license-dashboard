# ai_utils.py
import json
import google.generativeai as genai

def clean_name_with_gemini(raw_first_name: str, last_name: str, api_key: str) -> str:
    """
    Uses the Gemini API to clean a name and returns the result.
    It now returns a tuple: (success_boolean, result_string)
    """
    if not api_key or "YOUR_API_KEY" in api_key:
        return False, "API key not configured"
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        You are an expert data cleaner preparing names for a legal directory search.
        Your task is to extract the most probable first name and ensure it contains ONLY alphabetic characters.
        - Strict Rule: Remove all non-alphabetic symbols like periods (.), hyphens (-), and quotation marks (').
        - For "W. Michael", the first name is "Michael".
        - For "Joseph 'Joe'", the first name is "Joseph".
        - For a single initial like "R.", the first name must be cleaned to "R".
        - For a hyphenated name like "Mary-Beth", the first name is "Mary".
        Analyze the following full name:
        First Name (raw): "{raw_first_name}"
        Last Name: "{last_name}"
        Return a JSON object with a single key "cleaned_first_name".
        """
        response = model.generate_content(prompt, request_options={"timeout": 30})
        data = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
        cleaned_name = data.get("cleaned_first_name")

        if not cleaned_name:
            return False, "AI returned an empty response"
        
        return True, cleaned_name
    except Exception as e:
        return False, f"AI cleaning error: {e}"