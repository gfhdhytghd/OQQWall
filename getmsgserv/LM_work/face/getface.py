import re
import requests

def download_images_from_md(filename):
    # Read the Markdown file
    with open(filename, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Regular expression to extract ID and image URL
    matches = re.findall(r'\| (\d+) \| !\[\]\((https:\/\/rawgit\.com[^)]+)\) \|', content)
    
    for match in matches:
        image_id, image_url = match
        response = requests.get(image_url)
        if response.status_code == 200:
            with open(f"{image_id}.png", 'wb') as f:
                f.write(response.content)
            print(f"Downloaded {image_id}.png")
        else:
            print(f"Failed to download image with ID {image_id}")

# Replace 'src.md' with the path to your markdown file
download_images_from_md('src.md')