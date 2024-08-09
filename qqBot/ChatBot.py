import asyncio
import with_ai_agents
import sys

def read_config(file_path):
    config = {}
    with open(file_path, 'r') as f:
        for line in f:
            key, value = line.strip().split('=')
            config[key.strip()] = value.strip().strip('"')
    return config

config = read_config('oqqwall.config')

with_ai_agents.api_key = config.get('apikey')
with_ai_agents.platform = 'dashscope'
with_ai_agents.model_name = "qwen2-72b-instruct"

text = sys.argv[1]
res = asyncio.run(with_ai_agents.handler.ask_central_brain(text))
print(res)