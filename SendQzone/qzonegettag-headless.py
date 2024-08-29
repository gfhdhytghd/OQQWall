import time
import json
import re
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

def connect_to_chrome():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument('--disable-gpu')
    browser = webdriver.Chrome(options=chrome_options)
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

def find_number(text):
    match = re.search(r'#(\d+)', text)
    if match:
        return match.group(1)
    return None

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
    # 读取配置并连接到Chrome
    config = read_config('oqqwall.config')
    my_qq = sys.argv[1]

    # 连接到守护进程中的Chrome实例
    browser = connect_to_chrome()

    # 登录QQ Zone
    login(browser, my_qq)

    # 进入朋友的QQ Zone
    print('Trying to get into the QQ Zone')
    browser.get(f'https://user.qzone.qq.com/{my_qq}/311')
    print('Get in!')

    # 获取内容
    while True:
        # 移动到QQ Zone框架
        iframe = browser.find_element(By.ID, 'app_canvas_frame')
        wait_element = WebDriverWait(browser, 20)
        wait_element.until(EC.frame_to_be_available_and_switch_to_it(iframe))

        # 获取网页源代码
        time.sleep(2)
        html = browser.page_source
        found_number = get(html)
        if found_number:
            break

        # 翻到下一页
        num_retry = 0
        while True:
            try:
                nextpage = browser.find_element(By.XPATH, '//a[@title="下一页"]')
                nextpage.click()
                print('\033[0;33m\nMove to the next page!\033[0m')
                break
            except Exception as error:
                num_retry += 1
                print(f'\033[0;31mNext page error! {error} \033[0m')
                print(f'\033[0;32mRetry for {num_retry} time(s)\033[0m')
                time.sleep(1)

        browser.switch_to.default_content()

    browser.quit()

if __name__ == '__main__':
    main()
