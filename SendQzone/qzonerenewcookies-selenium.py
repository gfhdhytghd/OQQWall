import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

def connect_to_chrome():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument('--disable-gpu')
    browser = webdriver.Chrome(options=chrome_options)
    return browser

# Log in to QQ Zone
def login(browser, my_qq):
    browser.get('https://i.qq.com/')
    browser.switch_to.frame("login_frame")
    time.sleep(2)
    try:
        find = browser.find_element(By.ID, f'img_out_{my_qq}')
        find.click()
        time.sleep(3)
    except Exception as error:
        print(f'Log Error! {error}')
    else:
        print("Successfully Logged!")
        browser.switch_to.default_content()

    try:
        cookies = browser.get_cookies()
        cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}
        with open("cookies.json", "w") as f:
            json.dump(cookies_dict, f, indent=4)
    except Exception as error:
        print(f'Cookies Save Error! {error}')
    else:
        print("Successfully Saved Cookies!")
        browser.switch_to.default_content()

def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config

def main():
    # Read configuration and connect to Chrome
    config = read_config('oqqwall.config')
    my_qq = config.get('mainqq-id')

    # Connect to the Chrome instance running in the daemon
    browser = connect_to_chrome()
    
    # Log in and save cookies
    login(browser, my_qq)
    browser.quit()

if __name__ == '__main__':
    main()
