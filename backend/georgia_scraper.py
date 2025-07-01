# backend/georgia_scraper.py

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from ai_utils import clean_name_with_gemini

# This is no longer a generator. It's a regular function.
def run_georgia_verification(georgia_df, gemini_api_key, log_func):
    log_func("--- [Module Start] Starting Georgia Bar Verification ---")
    
    output_data = []
    base_url = "https://www.gabar.org/member-directory/"

    for index, row in georgia_df.iterrows():
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

            raw_first_name = str(row.get('first name', '')).strip()
            last_name = str(row.get('last name', '')).strip()
            admit_date_to_find = str(row.get('admit date', '')).strip()
            
            if not raw_first_name and not last_name: continue

            log_func(f"\n  [Record {index+1}] Processing: '{raw_first_name} {last_name}'")
            current_result = {'first name': raw_first_name, 'last name': last_name, 'admit date': admit_date_to_find, 'state': 'georgia', 'status': '', 'discipline': '', 'profile links': '', 'unmatched profile links': ''}
            
            success, result = clean_name_with_gemini(raw_first_name, last_name, gemini_api_key)
            if success:
                log_func(f"    -> AI cleaned '{raw_first_name}' to '{result}'.")
                first_name = result
            else:
                log_func(f"    -> WARNING: {result}. Using basic cleaning.")
                first_name = "".join(filter(str.isalpha, raw_first_name.split()[0])) if raw_first_name else ""

            if not first_name or not last_name:
                log_func(f"    -> SKIPPED: Missing name after cleaning.")
                continue
            try:
                admit_date_to_find_norm = pd.to_datetime(admit_date_to_find).strftime('%#m/%#d/%Y').replace('//','/')
            except (ValueError, TypeError):
                log_func(f"    -> SKIPPED: Invalid date format: '{admit_date_to_find}'")
                current_result['status'] = 'Error - Invalid Date Format'
                output_data.append(current_result)
                continue
            
            log_func(f"    -> Navigating and searching for '{first_name} {last_name}'...")
            
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
                log_func("    -> STATUS: Not Found on website.")
                current_result['status'] = 'Not Found'
                output_data.append(current_result)
                continue
            
            profile_urls = [elem.get_attribute('href') for elem in driver.find_elements(*results_locator)]
            log_func(f"    -> Found {len(profile_urls)} potential profile(s).")

            match_found = False
            unmatched_links = []
            for i, url in enumerate(profile_urls):
                log_func(f"      -> [Candidate {i+1}/{len(profile_urls)}] Verifying profile: {url}")
                driver.get(url)
                unmatched_links.append(url)
                try:
                    admit_date_element = wait.until(EC.visibility_of_element_located((By.XPATH, "//p[@class='detail-item'][span[text()='Admit Date']]")))
                    extracted_admit_date = admit_date_element.text.split('Admit Date')[-1].strip()
                    extracted_admit_date_norm = pd.to_datetime(extracted_admit_date).strftime('%#m/%#d/%Y').replace('//','/')
                    
                    log_func(f"        - Comparing website date '{extracted_admit_date_norm}' with input date '{admit_date_to_find_norm}'")

                    if extracted_admit_date_norm == admit_date_to_find_norm:
                        log_func(f"        -> EXACT MATCH FOUND! Extracting details...")
                        status_xpath = "//p[@class='detail-item'][span[text()='Status']]"
                        discipline_xpath = "//div[@class='detail-item mb-3'][span[text()='Public Discipline']]"
                        wait.until(lambda d: "Loading..." not in d.find_element(By.XPATH, status_xpath).text)
                        status = driver.find_element(By.XPATH, status_xpath).text.replace('Status', '').strip()
                        log_func(f"        - Status: {status}")
                        wait.until(lambda d: "Loading..." not in d.find_element(By.XPATH, discipline_xpath).text)
                        discipline = driver.find_element(By.XPATH, discipline_xpath).text.replace('Public Discipline', '').strip()
                        log_func(f"        - Discipline: {discipline}")
                        current_result.update({'status': status, 'discipline': discipline, 'profile links': url})
                        output_data.append(current_result)
                        match_found = True
                        break
                except (TimeoutException, NoSuchElementException, IndexError) as e:
                    log_func(f"      -> ERROR: Could not find details on profile {url}. Error: {e}")
                    continue
            if not match_found:
                log_func("    -> STATUS: Admit Date Mismatch.")
                current_result.update({'status': 'Admit Date Mismatch', 'unmatched profile links': ', '.join(unmatched_links)})
                output_data.append(current_result)
        
        except Exception as e:
            log_func(f"    -> An unexpected error occurred: {e}")
            current_result['status'] = 'Processing Error'
            output_data.append(current_result)
        
        finally:
            if driver:
                driver.quit()
    
    return pd.DataFrame(output_data)