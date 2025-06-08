import os
import sys
import json
import sqlite3
from http import HTTPStatus
from PIL import Image
import dashscope
from dashscope import MultiModalConversation

CONFIG_PATH = 'oqqwall.config'
DB_PATH = './cache/OQQWall.db'


def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                config[key.strip()] = value.strip().strip('"')
    return config


def compress_image(path, max_pixels, size_limit):
    with Image.open(path) as img:
        width, height = img.size
        pixels = width * height
        if pixels > max_pixels:
            ratio = (max_pixels / pixels) ** 0.5
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            img.save(path)
        if os.path.getsize(path) > size_limit:
            quality = 90
            while os.path.getsize(path) > size_limit and quality > 10:
                img.save(path, quality=quality, optimize=True)
                quality -= 5


def image_safe(path, model, api_key):
    messages = [{
        'role': 'user',
        'content': [
            {'image': 'file://' + os.path.abspath(path)},
            {'text': '这张图片是否含有暴力、血腥、色情或其他违法内容？如果安全仅回答safe，否则回答unsafe'}
        ]
    }]
    try:
        rsp = MultiModalConversation.call(model=model, messages=messages, api_key=api_key)
        if rsp.status_code == HTTPStatus.OK:
            content = rsp.output.get('choices', [])[0].get('message', {}).get('content', '')
            return 'unsafe' not in content.lower()
    except Exception:
        pass
    return True


def update_safemsg(tag, safe):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute('SELECT AfterLM FROM preprocess WHERE tag=?', (tag,)).fetchone()
    if not row:
        conn.close()
        return
    data = json.loads(row[0])
    if not safe:
        data['safemsg'] = 'false'
    updated = json.dumps(data, ensure_ascii=False)
    cur.execute('UPDATE preprocess SET AfterLM=? WHERE tag=?', (updated, tag))
    conn.commit()
    conn.close()


def main(tag):
    config = read_config(CONFIG_PATH)
    api_key = config.get('apikey')
    max_pixels = int(config.get('vision_pixel_limit', 12000000))
    size_limit = float(config.get('vision_size_limit_mb', 9.5)) * 1024 * 1024
    model = config.get('vision_model', 'qwen-vl-max-latest')
    dashscope.api_key = api_key
    folder = os.path.join('cache/picture', str(tag))
    safe = True
    if os.path.isdir(folder):
        for file in os.listdir(folder):
            path = os.path.join(folder, file)
            compress_image(path, max_pixels, size_limit)
            if not image_safe(path, model, api_key):
                safe = False
    update_safemsg(tag, safe)


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        main(sys.argv[1])
