import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import re
import json
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.options import Options

# Log in to QQ Zone
def login(my_qq):
    global browser
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    browser = webdriver.Chrome(options=chrome_options)
    browser.get('https://i.qq.com/')
    time.sleep(2)
    browser.switch_to.frame("login_frame")

    try:
        find = browser.find_element(By.ID, f'img_out_{my_qq}')
        find.click()
        time.sleep(2)
    except Exception as error:
        print(f'Log Error! {error}')
    else:
        print("Successfully Logged!")
        browser.switch_to.default_content()
    try:
        cookies = browser.get_cookies()
        cookies_dict = {}
        for cookie in cookies:
            # Add cookies to the dictionary in the desired format
            cookies = browser.get_cookies()
            cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}
            with open("cookies.json", "w") as f:
                json.dump(cookies_dict, f, indent=4)  # Save cookies as JSON with indentation for readability
        with open("cookies.json", "w") as f:
                    json.dump(cookies_dict, f, indent=4)
    except Exception as error:
        print(f'Cookies Save Error! {error}')
    else:
        print("Successfully Saved Cookies!")
        browser.switch_to.default_content()
    return browser

# Use regular expression to find "#number" pattern
def find_number(text):
    match = re.search(r'#(\d+)', text)
    if match:
        return match.group(1)
    return None

# Get the text from the website and analyze it
def get(html):
    print('Trying to get shuoshuos')
    soup = BeautifulSoup(html, "html.parser")
    shuoshuos = soup.find_all(name="li", attrs={"class": "feed"})
    print(f'There are {len(shuoshuos)} messages.')

    for shuoshuo in shuoshuos:
        text = shuoshuo.get_text()
        print(text)

        number = find_number(text)
        if number:
            with open('./numb.txt', 'w', encoding='utf-8') as f:
                f.write(number)
            print(f"Found number: {number}")
            return True  # Found the number, exit the function

    return False  # Number not found, continue to next page

def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config

def main():
    # Log in
    config = read_config('oqqwall.config')
    friendlist = config.get('mainqq-id')
    my_qq = config.get('secondaryqq-id')
    driver = login(my_qq)

    # Get to the friend's QQ Zone
    print('Trying to get into the QQ Zone')
    driver.get(f'https://user.qzone.qq.com/{friendlist}/311')
    print('Get in!')

    # Get the contents
    while True:
        # Move to the QQ Zone frame
        iframe = driver.find_element(By.ID, 'app_canvas_frame')
        wait_element = WebDriverWait(driver, 20)
        wait_element.until(EC.frame_to_be_available_and_switch_to_it(iframe))

        # Get the HTML source code
        time.sleep(2)
        html = driver.page_source
        found_number = get(html)
        if found_number:
            break

        # Go to the next page
        num_retry = 0
        while True:
            try:
                nextpage = driver.find_element(By.XPATH, '//a[@title="下一页"]')
                nextpage.click()
                print('\033[0;33m\nMove to the next page!\033[0m')
                break
            except Exception as error:
                num_retry += 1
                print(f'\033[0;31mNext page error! {error} \033[0m')
                print(f'\033[0;32mRetry for {num_retry} time(s)\033[0m')
                time.sleep(1)

        driver.switch_to.default_content()
    driver.close()

if __name__ == '__main__':
    main()
