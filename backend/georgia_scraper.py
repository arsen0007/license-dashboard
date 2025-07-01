# backend/georgia_scraper.py

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
from ai_utils import clean_name_with_gemini
import json

# Import the shared state for the stop functionality
import shared_state

def run_georgia_verification(georgia_df: pd.DataFrame, gemini_api_key: str):
    yield "--- [Module Start] Starting Georgia Bar Verification ---\n"
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(service=service, options=options)
        
        output_data = []
        base_url = "https://www.gabar.org/member-directory/"

        for index, row in georgia_df.iterrows():
            # --- Stop Button Check ---
            if shared_state.STOP_REQUESTED:
                yield "--- [Module Stop] Verification stopped by user. ---\n"
                break
            # ---

            raw_first_name = row.get('first name', '')
            last_name = row.get('last name', '')
            admit_date_to_find = row.get('admit date', '')
            
            yield f"\n  [Record {index+1}] Processing: '{raw_first_name} {last_name}'\n"
            current_result = {'first name': raw_first_name, 'last name': last_name, 'admit date': admit_date_to_find, 'state': 'georgia', 'status': '', 'discipline': '', 'profile links': '', 'unmatched profile links': ''}
            
            success, result = clean_name_with_gemini(raw_first_name, last_name, gemini_api_key)
            if success:
                yield f"    -> AI cleaned '{raw_first_name}' to '{result}'.\n"
                first_name = result
            else:
                yield f"    -> WARNING: {result}. Using basic cleaning.\n"
                first_name = "".join(filter(str.isalpha, raw_first_name.split()[0])) if raw_first_name else ""

            if not first_name or not last_name:
                yield f"    -> SKIPPED: Missing name after cleaning.\n"
                continue
            try:
                admit_date_to_find_norm = pd.to_datetime(admit_date_to_find).strftime('%#m/%#d/%Y').replace('//','/')
            except (ValueError, TypeError):
                yield f"    -> SKIPPED: Invalid date format: '{admit_date_to_find}'\n"
                current_result['status'] = 'Error - Invalid Date Format'
                output_data.append(current_result)
                continue
            
            yield f"    -> Navigating and searching for '{first_name} {last_name}'...\n"
            
            try:
                driver.get(base_url)
                wait = WebDriverWait(driver, 20)
                first_name_field = wait.until(EC.presence_of_element_located((By.NAME, "firstName")))
                last_name_field = driver.find_element(By.NAME, "lastName")
                search_button = driver.find_element(By.XPATH, "//div[contains(@class, 'd-lg-flex')]//button[@type='submit']")
                first_name_field.clear(); first_name_field.send_keys(first_name)
                last_name_field.clear(); last_name_field.send_keys(last_name)
                search_button.click()

                no_results_locator = (By.XPATH, "//*[contains(text(), 'No results found')]")
                results_locator = (By.XPATH, "//a[contains(@href, '/member-directory/?id=')]")

                wait.until(EC.any_of(EC.presence_of_element_located(no_results_locator), EC.presence_of_element_located(results_locator)))

                if driver.find_elements(*no_results_locator):
                    yield "    -> STATUS: Not Found on website.\n"
                    current_result['status'] = 'Not Found'
                    output_data.append(current_result)
                    continue
                
                profile_links_elements = driver.find_elements(*results_locator)
                profile_urls = [elem.get_attribute('href') for elem in profile_links_elements]
                yield f"    -> Found {len(profile_urls)} potential profile(s).\n"

                match_found = False
                unmatched_links = []
                for i, url in enumerate(profile_urls):
                    if shared_state.STOP_REQUESTED: break
                    yield f"      -> [Candidate {i+1}/{len(profile_urls)}] Verifying profile: {url}\n"
                    driver.get(url)
                    unmatched_links.append(url)
                    try:
                        admit_date_element = wait.until(EC.visibility_of_element_located((By.XPATH, "//p[@class='detail-item'][span[text()='Admit Date']]")))
                        extracted_admit_date = admit_date_element.text.split('Admit Date')[-1].strip()
                        extracted_admit_date_norm = pd.to_datetime(extracted_admit_date).strftime('%#m/%#d/%Y').replace('//','/')
                        
                        yield f"        - Comparing website date '{extracted_admit_date_norm}' with input date '{admit_date_to_find_norm}'\n"

                        if extracted_admit_date_norm == admit_date_to_find_norm:
                            yield f"        -> EXACT MATCH FOUND! Extracting details...\n"

                            status_xpath = "//p[@class='detail-item'][span[text()='Status']]"
                            discipline_xpath = "//div[@class='detail-item mb-3'][span[text()='Public Discipline']]"
                            
                            # --- FIX: Wait for "Loading..." to disappear ---
                            wait.until(lambda d: "Loading..." not in d.find_element(By.XPATH, status_xpath).text)
                            status = driver.find_element(By.XPATH, status_xpath).text.replace('Status', '').strip()
                            yield f"        - Status: {status}\n"
                            
                            wait.until(lambda d: "Loading..." not in d.find_element(By.XPATH, discipline_xpath).text)
                            discipline = driver.find_element(By.XPATH, discipline_xpath).text.replace('Public Discipline', '').strip()
                            yield f"        - Discipline: {discipline}\n"
                            # --- END FIX ---

                            current_result['status'] = status
                            current_result['discipline'] = discipline
                            current_result['profile links'] = url
                            output_data.append(current_result)
                            match_found = True
                            break
                    except (TimeoutException, NoSuchElementException, IndexError) as e:
                        yield f"      -> ERROR: Could not find details on profile {url}. Error: {e}\n"
                        continue
                if not match_found and not shared_state.STOP_REQUESTED:
                    yield "    -> STATUS: Admit Date Mismatch. No profile with a matching admit date was found.\n"
                    current_result['status'] = 'Admit Date Mismatch'
                    current_result['unmatched profile links'] = ', '.join(unmatched_links)
                    output_data.append(current_result)
            except Exception as e:
                yield f"    -> An unexpected error occurred: {e}\n"
                current_result['status'] = 'Processing Error'
                output_data.append(current_result)
        
        if not shared_state.STOP_REQUESTED:
            yield "\n--- [Module End] Georgia verification complete. ---\n"
            final_results = pd.DataFrame(output_data).to_json(orient='records')
            yield f"__RESULTS__{final_results}"

    except Exception as e:
        yield f"!!! MODULE ERROR: An unexpected error occurred in the Georgia scraper: {e} !!!\n"
    finally:
        if driver:
            driver.quit()