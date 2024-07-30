import os
import sys
import json
import time
import base64
import requests
import asyncio
import re
import traceback
import typing


# URL definitions
qrcode_url = "https://ssl.ptlogin2.qq.com/ptqrshow?appid=549000912&e=2&l=M&s=3&d=72&v=4&t=0.31232733520361844&daid=5&pt_3rd_aid=0"
login_check_url = "https://xui.ptlogin2.qq.com/ssl/ptqrlogin?u1=https://qzs.qq.com/qzone/v5/loginsucc.html?para=izone&ptqrtoken={}&ptredirect=0&h=1&t=1&g=1&from_ui=1&ptlang=2052&action=0-0-1656992258324&js_ver=22070111&js_type=1&login_sig=&pt_uistyle=40&aid=549000912&daid=5&has_onekey=1&&o1vId=1e61428d61cb5015701ad73d5fb59f73"
check_sig_url = "https://ptlogin2.qzone.qq.com/check_sig?pttype=1&uin={}&service=ptqrlogin&nodirect=1&ptsigx={}&s_url=https://qzs.qq.com/qzone/v5/loginsucc.html?para=izone&f_url=&ptlang=2052&ptredirect=100&aid=549000912&daid=5&j_later=0&low_login_hour=0&regmaster=0&pt_login_type=3&pt_aid=0&pt_aaid=16&pt_light=0&pt_3rd_aid=0"

GET_VISITOR_AMOUNT_URL = "https://h5.qzone.qq.com/proxy/domain/g.qzone.qq.com/cgi-bin/friendshow/cgi_get_visitor_more?uin={}&mask=7&g_tk={}&page=1&fupdate=1&clear=1"
UPLOAD_IMAGE_URL = "https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image"
EMOTION_PUBLISH_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6"


def generate_gtk(skey: str) -> str:
    """生成gtk"""
    hash_val = 5381
    for i in range(len(skey)):
        hash_val += (hash_val << 5) + ord(skey[i])
    return str(hash_val & 2147483647)


def get_picbo_and_richval(upload_result):
    json_data = upload_result

    if 'ret' not in json_data:
        raise Exception("获取图片picbo和richval失败")

    if json_data['ret'] != 0:
        raise Exception("上传图片失败")
    picbo_spt = json_data['data']['url'].split('&bo=')
    if len(picbo_spt) < 2:
        raise Exception("上传图片失败")
    picbo = picbo_spt[1]

    richval = ",{},{},{},{},{},{},,{},{}".format(json_data['data']['albumid'], json_data['data']['lloc'],
                                                 json_data['data']['sloc'], json_data['data']['type'],
                                                 json_data['data']['height'], json_data['data']['width'],
                                                 json_data['data']['height'], json_data['data']['width'])

    return picbo, richval


class QzoneLogin:

    def __init__(self):
        pass

    def getptqrtoken(self, qrsig):
        e = 0
        for i in range(1, len(qrsig) + 1):
            e += (e << 5) + ord(qrsig[i - 1])
        return str(2147483647 & e)

    async def check_cookies(self, cookies: dict) -> bool:
        # Placeholder: Implement cookie validation logic
        return True

    async def login_via_qrcode(
        self,
        qrcode_callback: typing.Callable[[bytes], typing.Awaitable[None]],
        max_timeout_times: int = 3,
    ) -> dict:
        for i in range(max_timeout_times):
            # 图片URL
            req = requests.get(qrcode_url)

            qrsig = ''

            set_cookie = req.headers['Set-Cookie']
            set_cookies_set = req.headers['Set-Cookie'].split(";")
            for set_cookies in set_cookies_set:
                if set_cookies.startswith("qrsig"):
                    qrsig = set_cookies.split("=")[1]
                    break
            if qrsig == '':
                raise Exception("qrsig is empty")

            # 获取ptqrtoken
            ptqrtoken = self.getptqrtoken(qrsig)

            await qrcode_callback(req.content)

            # 检查是否登录成功
            while True:
                await asyncio.sleep(2)
                req = requests.get(login_check_url.format(ptqrtoken), cookies={"qrsig": qrsig})
                if req.text.find("二维码已失效") != -1:
                    break
                if req.text.find("登录成功") != -1:
                    # 检出检查登录的响应头
                    response_header_dict = req.headers

                    # 检出url
                    url = eval(req.text.replace("ptuiCB", ""))[2]

                    # 获取ptsigx
                    m = re.findall(r"ptsigx=[A-z \d]*&", url)

                    ptsigx = m[0].replace("ptsigx=", "").replace("&", "")

                    # 获取uin
                    m = re.findall(r"uin=[\d]*&", url)
                    uin = m[0].replace("uin=", "").replace("&", "")

                    # 获取skey和p_skey
                    res = requests.get(check_sig_url.format(uin, ptsigx), cookies={"qrsig": qrsig},
                                       headers={'Cookie': response_header_dict['Set-Cookie']})

                    final_cookie = res.headers['Set-Cookie']

                    final_cookie_dict = {}
                    for set_cookie in final_cookie.split(";, "):
                        for cookie in set_cookie.split(";"):
                            spt = cookie.split("=")
                            if len(spt) == 2 and final_cookie_dict.get(spt[0]) is None:
                                final_cookie_dict[spt[0]] = spt[1]

                    return final_cookie_dict
        raise Exception("{}次尝试失败".format(max_timeout_times))


class QzoneAPI:

    def __init__(self, cookies_dict: dict = {}):
        self.cookies = cookies_dict
        self.gtk2 = ''
        self.uin = 0

        if 'p_skey' in self.cookies:
            self.gtk2 = generate_gtk(self.cookies['p_skey'])

        if 'uin' in self.cookies:
            self.uin = int(self.cookies['uin'][1:])

    async def do(
        self,
        method: str,
        url: str,
        params: dict = {},
        data: dict = {},
        headers: dict = {},
        cookies: dict = None,
        timeout: int = 10
    ) -> requests.Response:

        if cookies is None:
            cookies = self.cookies

        return requests.request(
            method=method,
            url=url,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            timeout=timeout
        )

    async def token_valid(self, retry=3) -> bool:

        for i in range(retry):
            try:
                print(1)
                return True
            except Exception as e:
                traceback.print_exc()
                if i == retry - 1:
                    return False

    def image_to_base64(self, image: bytes) -> str:
        pic_base64 = base64.b64encode(image)
        return str(pic_base64)[2:-1]


    async def upload_image(self, image: bytes) -> str:
        """上传图片"""

        res = await self.do(
            method="POST",
            url=UPLOAD_IMAGE_URL,
            data={
                "filename": "filename",
                "zzpanelkey": "",
                "uploadtype": "1",
                "albumtype": "7",
                "exttype": "0",
                "skey": self.cookies["skey"],
                "zzpaneluin": self.uin,
                "p_uin": self.uin,
                "uin": self.uin,
                "p_skey": self.cookies['p_skey'],
                "output_type": "json",
                "qzonetoken": "",
                "refer": "shuoshuo",
                "charset": "utf-8",
                "output_charset": "utf-8",
                "upload_hd": "1",
                "hd_width": "2048",
                "hd_height": "10000",
                "hd_quality": "96",
                "backUrls": "http://upbak.photo.qzone.qq.com/cgi-bin/upload/cgi_upload_image,http://119.147.64.75/cgi-bin/upload/cgi_upload_image",
                "url": "https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image?g_tk=" + self.gtk2,
                "base64": "1",
                "picfile": self.image_to_base64(image),
            },
            headers={
                'referer': 'https://user.qzone.qq.com/' + str(self.uin),
                'origin': 'https://user.qzone.qq.com'
            },
            timeout=60
        )
        if res.status_code == 200:
            return eval(res.text[res.text.find('{'):res.text.rfind('}') + 1])
        else:
            raise Exception("上传图片失败")

    async def publish_emotion(self, content: str, images: list[bytes] = []) -> str:
        """发表说说
        :return: 说说tid
        :except: 发表失败
        """

        if images is None:
            images = []

        post_data = {

            "syn_tweet_verson": "1",
            "paramstr": "1",
            "who": "1",
            "con": content,
            "feedversion": "1",
            "ver": "1",
            "ugc_right": "1",
            "to_sign": "0",
            "hostuin": self.uin,
            "code_version": "1",
            "format": "json",
            "qzreferrer": "https://user.qzone.qq.com/" + str(self.uin)
        }

        if len(images) > 0:

            # 挨个上传图片
            pic_bos = []
            richvals = []
            for img in images:
                uploadresult = await self.upload_image(img)
                picbo, richval = get_picbo_and_richval(uploadresult)
                pic_bos.append(picbo)
                richvals.append(richval)

            post_data['pic_bo'] = ','.join(pic_bos)
            post_data['richtype'] = '1'
            post_data['richval'] = '\t'.join(richvals)

        res = await self.do(
            method="POST",
            url=EMOTION_PUBLISH_URL,
            params={
                'g_tk': self.gtk2,
                'uin': self.uin,
            },
            data=post_data,
            headers={
                'referer': 'https://user.qzone.qq.com/' + str(self.uin),
                'origin': 'https://user.qzone.qq.com'
            }
        )
        if res.status_code == 200:
            return res.json()['tid']
        else:
            raise Exception("发表说说失败: " + res.text)


async def main():
    if len(sys.argv) != 3:
        print("Usage: python3 test.py <message> <image_directory>")
        return

    message = sys.argv[1]
    image_directory = sys.argv[2]

    try:
        with open('./cookies.json', 'r') as f:
            cookies = json.load(f)
    except:
        cookies = None

    if not cookies:
        login = QzoneLogin()

        async def qrcode_callback(qrcode: bytes):
            with open("qrcode.png", "wb") as f:
                f.write(qrcode)

        try:
            cookies = await login.login_via_qrcode(qrcode_callback)
            print("Cookies after login:", cookies)
            with open('cookies.json', 'w') as f:
                json.dump(cookies, f)
            os.remove('./qrcode.png')
        except Exception as e:
            print("Failed to generate login QR code.")
            traceback.print_exc()
            return

    print("Final cookies:", cookies)

    qzone = QzoneAPI(cookies)

    if not await qzone.token_valid():
        print("Cookies expired or invalid")
        return

    image_files = sorted(
        [os.path.join(image_directory, f) for f in os.listdir(image_directory) if os.path.isfile(os.path.join(image_directory, f))]
    )

    images = []
    for image_file in image_files:
        with open(image_file, "rb") as img:
            images.append(img.read())

    try:
        tid = await qzone.publish_emotion(message, images)
        print(f"Successfully published with tid: {tid}")
    except Exception as e:
        print("Failed to publish.")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
