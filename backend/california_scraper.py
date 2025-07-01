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
from ai_utils import clean_name_with_gemini

def run_california_verification(california_df, gemini_api_key, log_func):
    log_func("--- [Module Start] Starting California Bar Verification ---")
    
    output_data = []
    base_url = "https://apps.calbar.ca.gov/attorney/LicenseeSearch/QuickSearch"

    for index, row in california_df.iterrows():
        driver = None
        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option('excludeSwitches', ['enable-logging'])
            options.add_argument("--headless")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--single-process")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            wait = WebDriverWait(driver, 15)

            raw_first_name = str(row.get('first name', '')).strip()
            last_name = str(row.get('last name', '')).strip()
            admit_date_to_find = str(row.get('admit date', '')).strip()

            if not raw_first_name and not last_name: continue

            log_func(f"\n  [Record {index+1}] Processing: '{raw_first_name} {last_name}'")
            current_result = {'first name': raw_first_name, 'last name': last_name, 'admit date': admit_date_to_find, 'state': 'california', 'status': '', 'discipline': '', 'profile links': '', 'unmatched profile links': ''}

            success, result = clean_name_with_gemini(raw_first_name, last_name, gemini_api_key)
            if success:
                log_func(f"    -> AI cleaned '{raw_first_name}' to '{result}'.")
                first_name = result
            else:
                log_func(f"    -> WARNING: {result}. Using basic cleaning.")
                first_name = "".join(filter(str.isalpha, raw_first_name.split()[0])) if raw_first_name else ""
            
            search_name = f"{first_name} {last_name}".strip()

            if not search_name or not admit_date_to_find:
                log_func("    -> SKIPPED: Missing name or admit date after cleaning.")
                current_result['status'] = "Missing Input Data"
                output_data.append(current_result)
                continue

            try:
                input_admit_date_obj = datetime.strptime(admit_date_to_find, '%m/%d/%Y')
            except ValueError:
                log_func(f"    -> SKIPPED: Invalid date format '{admit_date_to_find}'.")
                current_result['status'] = "Invalid Input Date Format"
                output_data.append(current_result)
                continue

            log_func(f"    -> Navigating and searching for '{search_name}'...")
            driver.get(base_url)
            search_field = wait.until(EC.presence_of_element_located((By.ID, "FreeText")))
            search_button = driver.find_element(By.ID, "btn_quicksearch")
            search_field.clear(); search_field.send_keys(search_name)
            search_button.click()

            wait.until(EC.any_of(EC.presence_of_element_located((By.ID, "tblAttorney")), EC.presence_of_element_located((By.CLASS_NAME, "attSearchRes"))))

            if driver.find_elements(By.CLASS_NAME, "attSearchRes"):
                if "returned no results" in driver.find_element(By.CLASS_NAME, "attSearchRes").text:
                    log_func(f"    -> STATUS: Not Found on website.")
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
                            candidate_urls.append(cells[0].find_element(By.TAG_NAME, 'a').get_attribute('href'))
                    except (ValueError, NoSuchElementException):
                        continue
            
            log_func(f"    -> Found {len(candidate_urls)} potential profile(s) for admit month/year {input_admit_date_obj.strftime('%B %Y')}.")

            match_found = False
            unmatched_links = []
            for i, profile_url in enumerate(candidate_urls):
                log_func(f"      -> [Candidate {i+1}/{len(candidate_urls)}] Verifying profile: {profile_url}")
                unmatched_links.append(profile_url)
                driver.get(profile_url)
                try:
                    history_table = wait.until(EC.presence_of_element_located((By.XPATH, "//td[contains(text(), 'Admitted to the State Bar of California')]/ancestor::table")))
                    is_exact_match = False
                    for tr in history_table.find_elements(By.TAG_NAME, 'tr'):
                        if "Admitted to the State Bar of California" in tr.text:
                            extracted_date_str = tr.find_element(By.TAG_NAME, 'td').text.strip()
                            log_func(f"        - Comparing website date '{extracted_date_str}' with input date '{admit_date_to_find}'")
                            if extracted_date_str == admit_date_to_find:
                                is_exact_match = True
                                break
                    if is_exact_match:
                        log_func(f"        -> EXACT MATCH FOUND! Extracting details...")
                        status = driver.find_element(By.XPATH, "//b[contains(text(), 'License Status:')]/..").text.replace('License Status:', '').strip()
                        log_func(f"        - Status: {status}")
                        discipline_cell = history_table.find_element(By.XPATH, ".//tr[td[strong[text()='Present']]]").find_elements(By.TAG_NAME, 'td')[2]
                        discipline = discipline_cell.text.strip() if discipline_cell.text.strip() else "No discipline found"
                        log_func(f"        - Discipline: {discipline}")
                        current_result.update({'status': status, 'discipline': discipline, 'profile links': profile_url})
                        match_found = True
                        break
                except (TimeoutException, NoSuchElementException):
                    log_func(f"      -> ERROR: Could not find details table on profile {profile_url}")
                    continue
            
            if not match_found:
                 log_func("    -> STATUS: Verification Failed. No profile with an exact date match was found.")
                 current_result['status'] = "Verification Failed"
            
            current_result['unmatched profile links'] = ", ".join(unmatched_links)
            output_data.append(current_result)

        except Exception as e:
            log_func(f"    -> An unexpected error occurred: {e}")
            current_result['status'] = 'Processing Error'
            output_data.append(current_result)
        finally:
            if driver:
                driver.quit()
    
    return pd.DataFrame(output_data)