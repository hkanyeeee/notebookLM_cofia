#!/usr/bin/env python3
"""Web 搜索工具测试脚本"""

import asyncio
import json
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.tools.registry import tool_registry
from app.tools.orchestrator import initialize_orchestrator, get_orchestrator
from app.tools.models import ToolCall, RunConfig, ToolMode
from app.config import LLM_SERVICE_URL


async def test_tool_registration():
    """测试工具注册"""
    print("=== 测试工具注册 ===")
    
    # 检查工具是否已注册
    if tool_registry.has_tools():
        print(f"✓ 注册表中有 {len(tool_registry.get_all_schemas())} 个工具")
        
        for schema in tool_registry.get_all_schemas():
            print(f"  - {schema.name}: {schema.description}")
        
        # 检查 web_search 工具
        web_search_schema = tool_registry.get_tool_schema("web_search")
        if web_search_schema:
            print("✓ Web 搜索工具已成功注册")
            print(f"  描述: {web_search_schema.description}")
            print(f"  参数: {list(web_search_schema.parameters.get('properties', {}).keys())}")
            return True
        else:
            print("✗ Web 搜索工具未找到")
            return False
    else:
        print("✗ 注册表中没有工具")
        return False


async def test_tool_execution():
    """测试工具执行"""
    print("\n=== 测试工具执行 ===")
    
    try:
        # 创建工具调用
        tool_call = ToolCall(
            name="web_search",
            arguments={
                "query": "Python 编程最佳实践",
                "retrieve_only": False
            },
            call_id="test_001"
        )
        
        print(f"执行工具调用: {tool_call.name}")
        print(f"参数: {tool_call.arguments}")
        
        # 执行工具
        result = await tool_registry.execute_tool(tool_call)
        
        if result.success:
            print("✓ 工具执行成功")
            
            # 解析结果
            try:
                result_data = json.loads(result.result)
                print(f"  会话ID: {result_data.get('session_id', 'N/A')}")
                print(f"  消息: {result_data.get('message', 'N/A')}")
                print(f"  搜索结果数: {result_data.get('search_count', 0)}")
                print(f"  召回内容数: {result_data.get('retrieved_count', 0)}")
                
                if result_data.get('top_results'):
                    print("  前几个相关结果:")
                    for i, item in enumerate(result_data['top_results'][:2], 1):
                        print(f"    {i}. 来源: {item.get('source', 'Unknown')}")
                        print(f"       分数: {item.get('score', 0):.3f}")
                        print(f"       预览: {item.get('content_preview', '')[:100]}...")
                
                return True
            except json.JSONDecodeError as e:
                print(f"✗ 结果解析失败: {e}")
                print(f"原始结果: {result.result}")
                return False
        else:
            print(f"✗ 工具执行失败: {result.error}")
            print(f"结果: {result.result}")
            return False
            
    except Exception as e:
        print(f"✗ 工具执行异常: {e}")
        return False


async def test_orchestrator_integration():
    """测试编排器集成"""
    print("\n=== 测试编排器集成 ===")
    
    try:
        # 初始化编排器
        initialize_orchestrator(LLM_SERVICE_URL)
        orchestrator = get_orchestrator()
        
        if not orchestrator:
            print("✗ 编排器初始化失败")
            return False
        
        print("✓ 编排器初始化成功")
        
        # 验证设置
        setup_info = await orchestrator.validate_setup()
        print(f"  有工具: {setup_info['has_tools']}")
        print(f"  工具数量: {setup_info['tool_count']}")
        print(f"  可用工具: {setup_info['available_tools']}")
        print(f"  支持的策略: {setup_info['supported_strategies']}")
        
        if setup_info['has_tools'] and 'web_search' in setup_info['available_tools']:
            print("✓ Web 搜索工具在编排器中可用")
            return True
        else:
            print("✗ Web 搜索工具在编排器中不可用")
            return False
            
    except Exception as e:
        print(f"✗ 编排器测试异常: {e}")
        return False


async def test_light_execution():
    """轻量测试：只测试检索功能"""
    print("\n=== 轻量测试（仅检索） ===")
    
    try:
        # 创建仅检索的工具调用
        tool_call = ToolCall(
            name="web_search",
            arguments={
                "query": "测试查询",
                "retrieve_only": True  # 只检索，不进行网络搜索
            },
            call_id="test_light"
        )
        
        print("执行仅检索测试...")
        result = await tool_registry.execute_tool(tool_call)
        
        if result.success:
            print("✓ 仅检索功能正常")
            result_data = json.loads(result.result)
            print(f"  消息: {result_data.get('message', 'N/A')}")
            return True
        else:
            print(f"✗ 仅检索功能失败: {result.error}")
            return False
            
    except Exception as e:
        print(f"✗ 轻量测试异常: {e}")
        return False


async def main():
    """主测试函数"""
    print("开始 Web 搜索工具集成测试...\n")
    
    tests = [
        ("工具注册", test_tool_registration),
        ("轻量测试", test_light_execution),
        ("编排器集成", test_orchestrator_integration),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"测试 {test_name} 遇到异常: {e}")
            results.append((test_name, False))
    
    print("\n=== 测试总结 ===")
    passed = 0
    for test_name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"{test_name}: {status}")
        if success:
            passed += 1
    
    print(f"\n总计: {passed}/{len(results)} 个测试通过")
    
    # 如果基础测试通过，可以选择性运行完整测试
    if passed >= 2:
        print("\n基础测试通过，你可以选择运行完整的网络搜索测试：")
        print("python test_web_search_tool.py --full")
    
    return passed == len(results)


async def full_test():
    """完整测试（包括网络搜索）"""
    print("开始完整的 Web 搜索测试（包括网络搜索）...\n")
    
    # 先运行基础测试
    registration_ok = await test_tool_registration()
    if not registration_ok:
        print("工具注册失败，停止测试")
        return False
    
    # 运行完整的工具执行测试
    execution_ok = await test_tool_execution()
    
    print(f"\n完整测试结果: {'通过' if execution_ok else '失败'}")
    return execution_ok


if __name__ == "__main__":
    if "--full" in sys.argv:
        success = asyncio.run(full_test())
    else:
        success = asyncio.run(main())
    
    sys.exit(0 if success else 1)
