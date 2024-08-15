import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

def connect_to_chrome():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument("--remote-debugging-port=9222")  # 确保与守护程序使用相同的端口

    # 连接到已经运行的Chrome实例
    browser = webdriver.Remote(
        command_executor='http://127.0.0.1:9222',  # 连接到守护程序
        options=chrome_options,
        desired_capabilities=DesiredCapabilities.CHROME
    )
    return browser

# Log in to QQ Zone
def login(browser, my_qq):
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
    # 读取配置并连接到Chrome
    config = read_config('oqqwall.config')
    my_qq = config.get('mainqq-id')

    # 连接到守护进程中的Chrome实例
    browser = connect_to_chrome()
    
    # 登录并保存Cookies
    login(browser, my_qq)
    browser.quit()

if __name__ == '__main__':
    main()
