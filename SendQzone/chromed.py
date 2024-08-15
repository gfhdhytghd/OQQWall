import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

def start_chrome_daemon():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument("--remote-debugging-port=9222")  # 设置远程调试端口

    # 启动ChromeDriver并设置为持续运行
    browser = webdriver.Chrome(options=chrome_options)

    print("Chrome daemon started and running on port 9222.")
    try:
        while True:
            time.sleep(10)  # 让守护程序持续运行
    except KeyboardInterrupt:
        print("Stopping Chrome daemon...")
    finally:
        browser.quit()

if __name__ == "__main__":
    start_chrome_daemon()
