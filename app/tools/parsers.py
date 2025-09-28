"""ReAct 和 Harmony 格式解析器"""
import re
import json
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any, Union
from .models import ToolCall


class ReActParser:
    """ReAct 格式解析器"""
    
    # ReAct 格式的正则表达式
    THOUGHT_PATTERN = re.compile(r'^Thought:\s*(.+?)(?=\n(?:Action|Final Answer)|\Z)', re.MULTILINE | re.DOTALL)
    ACTION_PATTERN = re.compile(r'^Action:\s*(.+?)(?=\n)', re.MULTILINE)
    ACTION_INPUT_PATTERN = re.compile(r'^Action Input:\s*(.+?)(?=\n(?:Observation|Thought|Action|Final Answer)|\Z)', re.MULTILINE | re.DOTALL)
    OBSERVATION_PATTERN = re.compile(r'^Observation:\s*(.+?)(?=\n(?:Thought|Action|Final Answer)|\Z)', re.MULTILINE | re.DOTALL)
    FINAL_ANSWER_PATTERN = re.compile(r'^Final Answer:\s*(.+)', re.MULTILINE | re.DOTALL)
    
    @classmethod
    def extract_thought(cls, text: str) -> Optional[str]:
        """提取思考内容"""
        match = cls.THOUGHT_PATTERN.search(text)
        return match.group(1).strip() if match else None
    
    @classmethod
    def extract_action(cls, text: str) -> Optional[str]:
        """提取动作名称"""
        match = cls.ACTION_PATTERN.search(text)
        return match.group(1).strip() if match else None
    
    @classmethod
    def extract_action_input(cls, text: str) -> Optional[Dict[str, Any]]:
        """提取动作输入参数"""
        match = cls.ACTION_INPUT_PATTERN.search(text)
        if not match:
            return None
        
        input_str = match.group(1).strip()
        try:
            # 尝试解析 JSON
            return json.loads(input_str)
        except json.JSONDecodeError:
            # 如果不是有效 JSON，尝试简单的键值对解析
            try:
                # 简单处理类似 key=value 的格式
                if '=' in input_str and '{' not in input_str:
                    result = {}
                    for part in input_str.split(','):
                        if '=' in part:
                            key, value = part.split('=', 1)
                            result[key.strip()] = value.strip().strip('"\'')
                    return result
                else:
                    # 作为单个字符串参数处理
                    return {"input": input_str}
            except:
                return {"input": input_str}
    
    @classmethod
    def extract_final_answer(cls, text: str) -> Optional[str]:
        """提取最终答案"""
        match = cls.FINAL_ANSWER_PATTERN.search(text)
        return match.group(1).strip() if match else None
    
    @classmethod
    def parse_tool_call(cls, text: str) -> Optional[ToolCall]:
        """从文本中解析工具调用"""
        action = cls.extract_action(text)
        if not action:
            return None
        
        action_input = cls.extract_action_input(text)
        if action_input is None:
            action_input = {}
        
        return ToolCall(
            name=action,
            arguments=action_input
        )
    
    @classmethod
    def is_final_answer(cls, text: str) -> bool:
        """检查是否包含最终答案"""
        return bool(cls.FINAL_ANSWER_PATTERN.search(text))


class HarmonyParser:
    """Harmony DSL 格式解析器"""
    
    # Harmony 格式的正则表达式（作为 XML 解析的备选方案）
    TOOL_TAG_PATTERN = re.compile(r'<tool\s+name\s*=\s*["\']([^"\']+)["\']\s*>(.*?)</tool>', re.DOTALL | re.IGNORECASE)
    
    # Channel Commentary 格式（GPT OSS特有格式）
    # 兼容多种变体，例如：
    # <|channel|>commentary to=web_search code<|message|>{...}
    # <|channel|>commentary to=web_search<|constrain|>json<|message|>{...}
    # 可选的 <|constrain|>json 与可选的 "code" 标记
    CHANNEL_PATTERN = re.compile(
        r'<\|channel\|>\s*commentary\s+to\s*=\s*([\w.-]+)\s*(?:code)?\s*(?:<\|constrain\|>\s*json)?\s*<\|message\|>\s*(\{[\s\S]*?\})',
        re.DOTALL | re.IGNORECASE
    )
    
    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """去除可能的 ``` 或 ```json 代码块包裹"""
        try:
            s = text.strip()
            if s.startswith("```") and s.endswith("```"):
                # 去除开头结尾围栏
                s = re.sub(r"^```(?:json)?\s*", "", s)
                s = re.sub(r"\s*```$", "", s)
            return s.strip()
        except Exception:
            return text

    @staticmethod
    def _extract_balanced_json(text: str, start_pos: int = 0) -> Optional[str]:
        """从 text[start_pos:] 位置开始，找到第一个 '{'，并基于花括号平衡提取完整 JSON 对象字符串。
        若失败返回 None。
        """
        try:
            i = text.find('{', start_pos)
            if i == -1:
                return None
            brace = 0
            in_str = False
            esc = False
            for j in range(i, len(text)):
                ch = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == '\\':
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == '{':
                        brace += 1
                    elif ch == '}':
                        brace -= 1
                        if brace == 0:
                            return text[i:j+1]
            return None
        except Exception:
            return None

    @classmethod
    def _apply_web_search_whitelist(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """对 web_search 参数进行白名单过滤与最小清理"""
        try:
            allowed = {"query", "filter_list", "model", "is_simple_query"}
            cleaned = {k: v for k, v in (args or {}).items() if k in allowed}
            return cleaned
        except Exception:
            return args or {}

    @classmethod
    def _normalize_tool_name(cls, name: str) -> str:
        try:
            if not isinstance(name, str):
                return name
            alias_map = {
                "websearch": "web_search",
                "search": "web_search",
                "web-search": "web_search",
                "WebSearch": "web_search",
                "internet_search": "web_search",
                "internet": "web_search",
                "browse": "web_search",
                "web": "web_search",
            }
            return alias_map.get(name, alias_map.get(name.lower(), name))
        except Exception:
            return name

    @classmethod
    def parse_xml_tools(cls, text: str) -> List[ToolCall]:
        """使用 XML 解析器提取工具调用（优先方法）"""
        tool_calls = []
        
        # 尝试提取所有 <tool> 标签
        tool_blocks = re.findall(r'<tool[^>]*>.*?</tool>', text, re.DOTALL | re.IGNORECASE)
        
        for block in tool_blocks:
            try:
                # 解析 XML
                root = ET.fromstring(block)
                name = root.get('name')
                
                if not name:
                    continue
                
                name = cls._normalize_tool_name(name)
                # 获取工具参数
                content = root.text or ""
                content = content.strip()
                content = cls._strip_code_fences(content)
                
                if content:
                    try:
                        # 先尝试直接解析
                        arguments = json.loads(content)
                    except json.JSONDecodeError:
                        # 退化：尝试从中抽取平衡 JSON
                        candidate = cls._extract_balanced_json(content, 0)
                        if candidate:
                            try:
                                arguments = json.loads(candidate)
                            except Exception:
                                arguments = {"input": content}
                        else:
                            # 如果不是 JSON，作为简单字符串处理
                            arguments = {"input": content}
                else:
                    arguments = {}
                
                if name == "web_search" and isinstance(arguments, dict):
                    arguments = cls._apply_web_search_whitelist(arguments)
                
                tool_calls.append(ToolCall(
                    name=name,
                    arguments=arguments
                ))
                
            except ET.ParseError:
                # XML 解析失败，尝试正则表达式
                continue
        
        return tool_calls
    
    @classmethod
    def parse_regex_tools(cls, text: str) -> List[ToolCall]:
        """使用正则表达式提取工具调用（备选方法）"""
        tool_calls = []
        
        matches = cls.TOOL_TAG_PATTERN.findall(text)
        
        for name, content in matches:
            content = content.strip()
            name = cls._normalize_tool_name(name)
            content = cls._strip_code_fences(content)
            
            if content:
                try:
                    arguments = json.loads(content)
                except json.JSONDecodeError:
                    candidate = cls._extract_balanced_json(content, 0)
                    if candidate:
                        try:
                            arguments = json.loads(candidate)
                        except Exception:
                            arguments = {"input": content}
                    else:
                        arguments = {"input": content}
            else:
                arguments = {}
            
            if name == "web_search" and isinstance(arguments, dict):
                arguments = cls._apply_web_search_whitelist(arguments)
            
            tool_calls.append(ToolCall(
                name=name,
                arguments=arguments
            ))
        
        return tool_calls
    
    @classmethod
    def parse_channel_commentary(cls, text: str) -> List[ToolCall]:
        """解析 Channel Commentary 格式（GPT OSS特有）"""
        tool_calls = []

        # 优先：更稳健的扫描与平衡抽取
        try:
            # 允许出现多个 Channel Commentary 片段
            channel_start_re = re.compile(r'<\|channel\|>\s*commentary\s+to\s*=\s*([\w\.-]+)[^<]*<\|message\|>', re.IGNORECASE)
            pos = 0
            while True:
                m = channel_start_re.search(text, pos)
                if not m:
                    break
                tool_name = m.group(1)
                tool_name = cls._normalize_tool_name(tool_name)
                # 从 <|message|> 后开始提取 JSON
                msg_pos = text.find('<|message|>', m.start())
                if msg_pos == -1:
                    pos = m.end()
                    continue
                json_start = msg_pos + len('<|message|>')
                json_block = text[json_start:]
                json_block = cls._strip_code_fences(json_block)
                candidate = cls._extract_balanced_json(json_block, 0)
                if not candidate:
                    pos = m.end()
                    continue
                try:
                    arguments = json.loads(candidate)
                except Exception:
                    pos = m.end()
                    continue

                if tool_name == "web_search" and isinstance(arguments, dict):
                    # 兼容清洗与白名单
                    if "topn" in arguments:
                        _ = arguments.pop("topn", None)
                        print("[HarmonyParser] 移除不支持的topn参数")
                    if "source" in arguments:
                        _ = arguments.pop("source", None)
                        print("[HarmonyParser] 移除source参数，由外部SearxNG控制")
                    if "categories" in arguments:
                        _ = arguments.pop("categories", None)
                        print("[HarmonyParser] 移除categories参数，由外部SearxNG控制")
                    for invalid in ("id", "cursor", "index", "page"):
                        if invalid in arguments:
                            _ = arguments.pop(invalid, None)
                            print(f"[HarmonyParser] 移除无效参数: {invalid}")
                    arguments = cls._apply_web_search_whitelist(arguments)

                tool_calls.append(ToolCall(name=tool_name, arguments=arguments))
                # 移动搜索位置，避免死循环
                pos = json_start + len(candidate)
        except Exception as e:
            print(f"[HarmonyParser] Channel Commentary 扫描异常: {e}")

        # 回退：原有的正则一次性匹配（可能会误切）
        if not tool_calls:
            matches = cls.CHANNEL_PATTERN.findall(text)
            for tool_name, json_content in matches:
                try:
                    tool_name = cls._normalize_tool_name(tool_name)
                    json_content = cls._strip_code_fences(json_content)
                    arguments = json.loads(json_content)
                    if tool_name == "web_search" and isinstance(arguments, dict):
                        for invalid in ("id", "cursor", "index", "page"):
                            if invalid in arguments:
                                _ = arguments.pop(invalid, None)
                                print(f"[HarmonyParser] 移除无效参数: {invalid}")
                        arguments = cls._apply_web_search_whitelist(arguments)
                    tool_calls.append(ToolCall(name=tool_name, arguments=arguments))
                except json.JSONDecodeError:
                    continue
        
        return tool_calls
    
    @classmethod
    def parse_tool_calls(cls, text: str) -> List[ToolCall]:
        """从文本中解析工具调用"""
        # 统一预处理：去围栏
        pre = cls._strip_code_fences(text or "")
        # 先尝试 Channel Commentary 格式（GPT OSS）
        tool_calls = cls.parse_channel_commentary(pre)
        
        if not tool_calls:
            # 优先使用 XML 解析
            tool_calls = cls.parse_xml_tools(pre)
        
        # 如果 XML 解析失败，使用正则表达式
        if not tool_calls:
            tool_calls = cls.parse_regex_tools(pre)
        
        return tool_calls
    
    @classmethod
    def has_tool_calls(cls, text: str) -> bool:
        """检查文本中是否包含工具调用"""
        return bool(cls.TOOL_TAG_PATTERN.search(text) or cls.CHANNEL_PATTERN.search(text))


class ToolCallValidator:
    """工具调用验证器"""
    
    @staticmethod
    def validate_json_schema(arguments: Dict[str, Any], schema: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """简单的 JSON Schema 验证
        
        Args:
            arguments: 工具参数
            schema: JSON Schema
            
        Returns:
            (是否有效, 错误信息)
        """
        try:
            # 检查必需字段
            required_fields = schema.get("properties", {}).keys()
            required = schema.get("required", [])
            
            for field in required:
                if field not in arguments:
                    return False, f"缺少必需字段: {field}"
            
            # 简单类型检查
            properties = schema.get("properties", {})
            for field, value in arguments.items():
                if field in properties:
                    expected_type = properties[field].get("type")
                    if expected_type == "string" and not isinstance(value, str):
                        return False, f"字段 {field} 应为字符串类型"
                    elif expected_type == "number" and not isinstance(value, (int, float)):
                        return False, f"字段 {field} 应为数字类型"
                    elif expected_type == "boolean" and not isinstance(value, bool):
                        return False, f"字段 {field} 应为布尔类型"
                    elif expected_type == "array" and not isinstance(value, list):
                        return False, f"字段 {field} 应为数组类型"
                    elif expected_type == "object" and not isinstance(value, dict):
                        return False, f"字段 {field} 应为对象类型"
            
            return True, None
            
        except Exception as e:
            return False, f"Schema 验证出错: {str(e)}"
    
    @staticmethod
    def sanitize_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """清理和标准化工具参数"""
        # 移除空值
        cleaned = {k: v for k, v in arguments.items() if v is not None}
        
        # 转换字符串数字
        for key, value in cleaned.items():
            if isinstance(value, str):
                # 尝试转换为数字
                try:
                    if value.isdigit():
                        cleaned[key] = int(value)
                    elif '.' in value:
                        cleaned[key] = float(value)
                except ValueError:
                    pass
                # 布尔值字符串
                low = value.strip().lower()
                if low in ("true", "false"):
                    cleaned[key] = (low == "true")
                # 逗号分隔数组
                if ',' in value and key.endswith(('_list', 's')):
                    arr = [item.strip() for item in value.split(',') if item.strip()]
                    if arr:
                        cleaned[key] = arr
        
        return cleaned
