#!/usr/bin/env python3
"""
测试脚本：验证 /agenttic-ingest 接口功能
"""

import asyncio
import httpx
import json

async def test_agenttic_ingest():
    """测试 agenttic-ingest 接口"""
    
    # 测试URL
    test_url = "https://lmstudio.ai/docs/python"
    
    # API请求数据 - 不再需要session_id参数
    payload = {
        "url": test_url,
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1024
    }
    
    # API端点
    api_url = "http://localhost:8000/agenttic-ingest"
    
    print("开始测试 /agenttic-ingest 接口...")
    print(f"测试URL: {test_url}")
    
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            print("发送请求...")
            response = await client.post(api_url, json=payload)
            
            print(f"响应状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ 接口调用成功!")
                print("响应数据:")
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("❌ 接口调用失败!")
                print(f"错误信息: {response.text}")
                
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    asyncio.run(test_agenttic_ingest())
