import requests
import json
from datetime import datetime

# 请求URL
# url = "http://192.168.31.125:5678/webhook-test/array2object"
url = "http://192.168.31.125:5678/webhook-test/array2array"

# 构造请求数据 - 与app/api/webhook.py中的WebhookData模型保持一致
data = {
    "document_name": "LM Studio Python开发指南",
    "collection_name": "lm_studio_python_guide",
    "url": "https://lmstudio.ai/docs/python",
    "total_chunks": 1,
    "task_name": "auto_ingest",
    "prompt": "你正在阅读一个网页的部分html，这个网页的url是https://lmstudio.ai/docs/python，内容是某个开源框架文档。现在我需要你识别这个文档下面的的子文档。比如：https://lmstudio.ai/docs/python/getting-started/project-setup是https://lmstudio.ai/docs/python的子文档。子文档的URL有可能在HTML中以a标签的href，button的跳转link等等形式存在，你需要调用你的编程知识进行识别，使用https://lmstudio.ai/docs/python进行拼接。最终将识别出来的子文档URL以数组的形式放在sub_docs属性联合chunk_id、index返回，注意：如果没有发现任何子文档，那么返回空数组",
    "data_list": [
        {
            "chunk_id": "8ad3044be359185182cfec6595a8d1e2",
            "content": "<!DOCTYPE html><html lang=\"en\" class=\"light\" style=\"color-scheme: light;\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><link rel=\"preload\" as=\"image\" imagesrcset=\"/next/image?url=%2F_next%2Fstatic%2Fmedia%2Flmstudio-app-logo.11b4d746.webp&amp;w=32&amp;q=75 1x, /_next/image?url=%2F_next%2Fstatic%2Fmedia%2Flmstudio-app-logo.11b4d746.webp&amp;w=64&amp;q=75 2x\" fetchpriority=\"high\"><link rel=\"stylesheet\" href=\"/next/static/css/4bc4902e4330e642.css\" data-precedence=\"next\"><link rel=\"stylesheet\" href=\"/next/static/css/9391d1957a88d9d7.css\" data-precedence=\"next\"><link rel=\"preload\" as=\"script\" fetchpriority=\"low\" href=\"/next/static/chunks/webpack-c83e7b297e2ebd7c.js\"><script src=\"/next/static/chunks/fd9d1056-ea999b7dd9a5dd54.js\" async=\"\"></script><script src=\"/next/static/chunks/5030-4a82632e735b3a82.js\" async=\"\"></script><script src=\"/next/static/chunks/main-app-dd53f9e0929c416a.js\" async=\"\"></script><script src=\"/next/static/chunks/ee560e2c-90ba2650af91130d.js\" async=\"\"></script><script src=\"/next/static/chunks/8e1d74a4-810ea8b66186d9e6.js\" async=\"\"></script><script src=\"/next/static/chunks/f8025e75-d80ef0bd06aa4704.js\" async=\"\"></script><script src=\"/next/static/chunks/eec3d76d-692d954fdc526554.js\" async=\"\"></script><script src=\"/next/static/chunks/2972-873a8cc42b23c71f.js\" async=\"\"></script><link rel=\"preload\" href=\"https://plausible.io/js/script.file-downloads.outbound-links.tagged-events.js\" as=\"script\"><title>lmstudio-python (Python SDK) | LM Studio Docs</title><meta name=\"description\" content=\"Getting started with LM Studio's Python SDK\"><meta property=\"og:title\" content=\"lmstudio-python (Python SDK) | LM Studio Docs\"><meta property=\"og:description\" content=\"Getting started with LM Studio's Python SDK\"><meta property=\"og:url\" content=\"/python\"><meta property=\"og:site_name\" content=\"LM Studio - Docs\"><meta property=\"og:image\" content=\"https://lmstudio.ai/api/og?title=lmstudio-python%20(Python%20SDK)&amp;from=docs/python&amp;description=Getting%20started%20with%20LM%20Studio%27s%20Python%20SDK\"><meta property=\"og:image:type\" content=\"image/png\"><meta property=\"og:image:width\" content=\"1200\"><meta property=\"og:image:height\" content=\"630\"><meta property=\"og:image:alt\" content=\"LM Studio: lmstudio-python (Python SDK)\"><meta property=\"og:type\" content=\"article\"><meta name=\"twitter:card\" content=\"summary_large_image\"><meta name=\"twitter:creator\" content=\" @lmstudio\"><meta name=\"twitter:title\" content=\"lmstudio-python (Python SDK) | LM Studio Docs\"><meta name=\"twitter:description\" content=\"Getting started with LM Studio's Python SDK\"><meta name",
            "index": 0
        }
    ],
    "recursive_depth": 2,
    "request_id": f"https://lmstudio.ai/docs/python_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
}

# 发送POST请求
response = requests.post(url, json=data)

# 输出响应结果
print("状态码:", response.status_code)
print("响应内容:", response.text)