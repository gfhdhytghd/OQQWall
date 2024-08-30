import asyncio
import json
import sys
import httpx
from httpx import Cookies

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"

async def get_clientkey(uin: str) -> str:
    local_key_url = "https://xui.ptlogin2.qq.com/cgi-bin/xlogin?s_url=https%3A%2F%2Fhuifu.qq.com%2Findex.html&style=20&appid=715021417" \
                    "&proxy_url=https%3A%2F%2Fhuifu.qq.com%2Fproxy.html"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(local_key_url, headers={"User-Agent": UA})
        pt_local_token = resp.cookies["pt_local_token"]
        client_key_url = f"https://localhost.ptlogin2.qq.com:4301/pt_get_st?clientuin={uin}&callback=ptui_getst_CB&r=0.7284667321181328&pt_local_tk={pt_local_token}"
        resp = await client.get(client_key_url, headers={"User-Agent": UA, "Referer": "https://ssl.xui.ptlogin2.qq.com/"}, cookies=resp.cookies)
        if resp.status_code == 400:
            raise Exception(f"获取clientkey失败: {resp.text}")
        clientKey = resp.cookies["clientkey"]
        return clientKey

async def get_cookies(uin: str, clientkey: str) -> dict:
    login_url = f"https://ssl.ptlogin2.qq.com/jump?ptlang=1033&clientuin={uin}&clientkey={clientkey}" \
        f"&u1=https%3A%2F%2Fuser.qzone.qq.com%2F{uin}%2Finfocenter&keyindex=19"
    async with httpx.AsyncClient(timeout=15.0) as client:   
        resp = await client.get(login_url, headers={"User-Agent": UA}, follow_redirects=False)
        resp = await client.get(resp.headers["Location"], headers={"User-Agent": UA, "Referer": "https://ssl.ptlogin2.qq.com/"}, cookies=resp.cookies, follow_redirects=False)
        cookies = {cookie.name: cookie.value for cookie in resp.cookies.jar}
        return cookies

async def save_cookies_to_file(cookies: dict, file_path: str):
    with open(file_path, "w") as f:
        json.dump(cookies, f, indent=4)
    print(f"Cookies saved to {file_path}")

async def main():
    # 读取 QQ 号码
    uin = sys.argv[1]
    
    # 获取 clientkey
    clientkey = await get_clientkey(uin)
    
    # 获取 cookies
    cookies = await get_cookies(uin, clientkey)
    
    # 保存 cookies 到文件
    await save_cookies_to_file(cookies, f"cookies-{uin}.json")

# 运行主函数
asyncio.run(main())
