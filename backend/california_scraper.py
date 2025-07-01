# backend/california_scraper.py

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from datetime import datetime
import time
from ai_utils import clean_name_with_gemini
import json

# Import the shared state for the stop functionality
import shared_state

def run_california_verification(california_df: pd.DataFrame, gemini_api_key: str):
    yield "--- [Module Start] Starting California Bar Verification ---\n"
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
        # --- OPTIMIZATIONS FOR LOW-RESOURCE ENVIRONMENTS ---
        options.add_argument("--no-sandbox") # A must-have for running in Docker
        options.add_argument("--disable-dev-shm-usage") # Overcomes limited shared memory problems
        options.add_argument("--disable-gpu") # Disables GPU hardware acceleration
        options.add_argument("--disable-extensions")
        options.add_argument("--single-process") # Runs Chrome in a single process
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 15)

        output_data = []
        base_url = "https://apps.calbar.ca.gov/attorney/LicenseeSearch/QuickSearch"

        for index, row in california_df.iterrows():
            # --- Stop Button Check ---
            if shared_state.STOP_REQUESTED:
                yield "--- [Module Stop] Verification stopped by user. ---\n"
                break
            # ---

            # --- FIX: More robust input validation ---
            raw_first_name = str(row.get('first name', '')).strip()
            last_name = str(row.get('last name', '')).strip()
            admit_date_to_find = str(row.get('admit date', '')).strip()

            # Skip the row if there's no name information at all. This handles blank lines in the CSV.
            if not raw_first_name and not last_name:
                continue # Silently skip fully empty name rows
            # --- END FIX ---

            yield f"\n  [Record {index+1}] Processing: '{raw_first_name} {last_name}'\n"

            current_result = {'first name': raw_first_name, 'last name': last_name, 'admit date': admit_date_to_find, 'state': 'california', 'status': '', 'discipline': '', 'profile links': '', 'unmatched profile links': ''}

            success, result = clean_name_with_gemini(raw_first_name, last_name, gemini_api_key)
            if success:
                yield f"    -> AI cleaned '{raw_first_name}' to '{result}'.\n"
                first_name = result
            else:
                yield f"    -> WARNING: {result}. Using basic cleaning.\n"
                first_name = "".join(filter(str.isalpha, raw_first_name.split()[0])) if raw_first_name else ""
            
            search_name = f"{first_name} {last_name}".strip()

            # --- FIX: Check for empty search name OR empty date after potential cleaning ---
            if not search_name or not admit_date_to_find:
                yield "    -> SKIPPED: Missing name or admit date after cleaning.\n"
                current_result['status'] = "Missing Input Data"
                output_data.append(current_result)
                continue
            # --- END FIX ---

            try:
                input_admit_date_obj = datetime.strptime(admit_date_to_find, '%m/%d/%Y')
            except ValueError:
                yield f"    -> SKIPPED: Invalid date format '{admit_date_to_find}'.\n"
                current_result['status'] = "Invalid Input Date Format"
                output_data.append(current_result)
                continue

            try:
                yield f"    -> Navigating and searching for '{search_name}'...\n"
                driver.get(base_url)
                search_field = wait.until(EC.presence_of_element_located((By.ID, "FreeText")))
                search_button = driver.find_element(By.ID, "btn_quicksearch")
                search_field.clear(); search_field.send_keys(search_name)
                search_button.click()

                wait.until(EC.any_of(EC.presence_of_element_located((By.ID, "tblAttorney")), EC.presence_of_element_located((By.CLASS_NAME, "attSearchRes"))))

                if driver.find_elements(By.CLASS_NAME, "attSearchRes"):
                    no_results_span = driver.find_element(By.CLASS_NAME, "attSearchRes")
                    if "returned no results" in no_results_span.text:
                        yield f"    -> STATUS: Not Found on website.\n"
                        current_result['status'] = 'Not Found'
                        output_data.append(current_result)
                        continue

                candidate_urls = []
                results_table = driver.find_element(By.ID, "tblAttorney")
                for profile_row in results_table.find_element(By.TAG_NAME, 'tbody').find_elements(By.TAG_NAME, 'tr'):
                    cells = profile_row.find_elements(By.TAG_NAME, 'td')
                    if len(cells) >= 5:
                        table_date_str = cells[4].text.strip()
                        try:
                            table_date_obj = datetime.strptime(table_date_str, '%B %Y')
                            if table_date_obj.year == input_admit_date_obj.year and table_date_obj.month == input_admit_date_obj.month:
                                link_tag = cells[0].find_element(By.TAG_NAME, 'a')
                                candidate_urls.append(link_tag.get_attribute('href'))
                        except (ValueError, NoSuchElementException):
                            continue
                
                yield f"    -> Found {len(candidate_urls)} potential profile(s) for admit month/year {input_admit_date_obj.strftime('%B %Y')}.\n"

                match_found = False
                unmatched_links = []
                for i, profile_url in enumerate(candidate_urls):
                    if shared_state.STOP_REQUESTED: break
                    yield f"      -> [Candidate {i+1}/{len(candidate_urls)}] Verifying profile: {profile_url}\n"
                    unmatched_links.append(profile_url)
                    driver.get(profile_url)
                    
                    try:
                        history_table = wait.until(EC.presence_of_element_located((By.XPATH, "//td[contains(text(), 'Admitted to the State Bar of California')]/ancestor::table")))
                        
                        is_exact_match = False
                        for tr in history_table.find_elements(By.TAG_NAME, 'tr'):
                            if "Admitted to the State Bar of California" in tr.text:
                                extracted_date_str = tr.find_element(By.TAG_NAME, 'td').text.strip()
                                yield f"        - Comparing website date '{extracted_date_str}' with input date '{admit_date_to_find}'\n"
                                if extracted_date_str == admit_date_to_find:
                                    is_exact_match = True
                                    break
                        
                        if is_exact_match:
                            yield f"        -> EXACT MATCH FOUND! Extracting details...\n"
                            current_result['profile links'] = profile_url
                            if profile_url in unmatched_links: unmatched_links.remove(profile_url)

                            status_p = driver.find_element(By.XPATH, "//b[contains(text(), 'License Status:')]/..")
                            status = status_p.text.replace('License Status:', '').strip()
                            yield f"        - Status: {status}\n"
                            current_result['status'] = status

                            present_row = history_table.find_element(By.XPATH, ".//tr[td[strong[text()='Present']]]")
                            discipline_cell = present_row.find_elements(By.TAG_NAME, 'td')[2]
                            discipline_text = discipline_cell.text.strip()
                            discipline = discipline_text if discipline_text and discipline_text != '\xa0' else "No discipline found"
                            yield f"        - Discipline: {discipline}\n"
                            current_result['discipline'] = discipline
                            
                            match_found = True
                            break
                    except (TimeoutException, NoSuchElementException):
                        yield f"      -> ERROR: Could not find details table on profile {profile_url}\n"
                        continue
                
                if not match_found and not shared_state.STOP_REQUESTED:
                     yield "    -> STATUS: Verification Failed. No profile with an exact date match was found.\n"
                     current_result['status'] = "Verification Failed"
                
                current_result['unmatched profile links'] = ", ".join(unmatched_links)
                output_data.append(current_result)

            except Exception as e:
                yield f"    -> An unexpected error occurred: {e}\n"
                current_result['status'] = 'Processing Error'
                output_data.append(current_result)
                
        if not shared_state.STOP_REQUESTED:
            yield "\n--- [Module End] California verification complete. ---\n"
            final_results = pd.DataFrame(output_data).to_json(orient='records')
            yield f"__RESULTS__{final_results}"

    except Exception as e:
        yield f"!!! MODULE ERROR: An unexpected error occurred in the California scraper: {e} !!!\n"
    finally:
        if driver:
            driver.quit()