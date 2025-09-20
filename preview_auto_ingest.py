#!/usr/bin/env python3
"""
Auto Ingest 预览脚本

这个脚本使用与 auto ingest 相同的方法拉取页面内容，
并显示拉取结果供人工确认是否包含子 URL。

使用方法:
    python preview_auto_ingest.py <URL>
    
或者交互式运行:
    python preview_auto_ingest.py
"""

import asyncio
import sys
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from typing import List, Tuple
import json

# 导入项目的获取和解析模块
from app.fetch_parse import fetch_html, fetch_then_extract, extract_text


def extract_links_from_html(html: str, base_url: str) -> List[Tuple[str, str]]:
    """
    从HTML中提取所有链接
    
    Args:
        html: HTML内容
        base_url: 基础URL，用于拼接相对链接
        
    Returns:
        List[Tuple[str, str]]: (链接文本, 完整URL) 的列表
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    
    # 获取所有a标签
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        text = a_tag.get_text(strip=True)
        
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
            
        # 转换为绝对URL
        full_url = urljoin(base_url, href)
        
        # 过滤掉明显不是子文档的链接
        if is_potential_sub_doc(full_url, base_url):
            links.append((text or "[无文本]", full_url))
    
    # 获取可能的按钮链接
    for button in soup.find_all("button"):
        onclick = button.get("onclick", "")
        if "location" in onclick or "href" in onclick:
            # 简单的onclick解析
            url_match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
            if url_match:
                href = url_match.group(1)
                full_url = urljoin(base_url, href)
                if is_potential_sub_doc(full_url, base_url):
                    text = button.get_text(strip=True)
                    links.append((text or "[按钮]", full_url))
    
    return links


def is_potential_sub_doc(url: str, base_url: str) -> bool:
    """
    判断是否可能是子文档链接
    
    Args:
        url: 要检查的URL
        base_url: 基础URL
        
    Returns:
        bool: 是否可能是子文档
    """
    try:
        parsed_url = urlparse(url)
        parsed_base = urlparse(base_url)
        
        # 必须是同域名
        if parsed_url.netloc != parsed_base.netloc:
            return False
            
        # URL路径应该以基础路径开头（表示是子路径）
        base_path = parsed_base.path.rstrip('/')
        url_path = parsed_url.path.rstrip('/')
        
        # 如果是更深层的路径，可能是子文档
        if url_path.startswith(base_path) and len(url_path) > len(base_path):
            return True
            
        # 如果在同一层级但不同文件，也可能是子文档
        if base_path and url_path.startswith(base_path.rsplit('/', 1)[0]):
            return True
            
        return False
        
    except Exception:
        return False


def display_content_preview(content: str, max_length: int = 1000) -> None:
    """显示内容预览"""
    print("\n" + "="*80)
    print("📄 页面内容预览")
    print("="*80)
    
    if len(content) <= max_length:
        print(content)
    else:
        print(content[:max_length])
        print(f"\n... (内容被截断，总长度: {len(content)} 字符)")
    
    print("="*80)


def display_links(links: List[Tuple[str, str]]) -> None:
    """显示找到的链接"""
    print(f"\n🔗 找到 {len(links)} 个潜在的子文档链接:")
    print("-"*80)
    
    if not links:
        print("❌ 未找到任何潜在的子文档链接")
        return
    
    for i, (text, url) in enumerate(links, 1):
        print(f"{i:2d}. {text[:50]:<50} -> {url}")
        if len(text) > 50:
            print(f"     完整文本: {text}")
        print()


def display_html_structure(html: str) -> None:
    """显示HTML结构概览"""
    soup = BeautifulSoup(html, "html.parser")
    
    print("\n🏗️  HTML结构概览:")
    print("-"*50)
    
    # 统计主要标签
    tag_counts = {}
    for tag in soup.find_all():
        tag_name = tag.name
        tag_counts[tag_name] = tag_counts.get(tag_name, 0) + 1
    
    # 显示最常见的标签
    common_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    for tag, count in common_tags:
        print(f"  {tag}: {count}")
    
    # 显示重要的结构元素
    important_tags = ['article', 'main', 'nav', 'aside', 'section', 'header', 'footer']
    found_structure = []
    for tag in important_tags:
        elements = soup.find_all(tag)
        if elements:
            found_structure.append(f"{tag}({len(elements)})")
    
    if found_structure:
        print(f"\n  结构元素: {', '.join(found_structure)}")


async def preview_url(url: str) -> None:
    """
    预览指定URL的内容和链接
    
    Args:
        url: 要预览的URL
    """
    print(f"🌐 正在分析URL: {url}")
    print("="*80)
    
    try:
        # 1. 获取原始HTML (与auto ingest相同的方法)
        print("📥 正在获取HTML内容...")
        html = await fetch_html(url, timeout=10.0)
        
        if not html:
            print("❌ 无法获取HTML内容")
            return
            
        print(f"✅ HTML获取成功 (长度: {len(html)} 字符)")
        
        # 2. 提取文本内容 (与auto ingest相同的方法)
        print("📝 正在提取文本内容...")
        try:
            text_content = extract_text(html, selector="article")
            print(f"✅ 文本提取成功 (长度: {len(text_content)} 字符)")
        except Exception as e:
            print(f"⚠️  文本提取失败: {e}")
            # 尝试使用渲染方法
            print("🔄 尝试使用渲染方法...")
            text_content = await fetch_then_extract(url, selector="article", timeout=10.0)
            print(f"✅ 渲染方法成功 (长度: {len(text_content)} 字符)")
        
        # 3. 分析HTML结构
        display_html_structure(html)
        
        # 4. 显示内容预览
        display_content_preview(text_content)
        
        # 5. 提取并显示链接
        links = extract_links_from_html(html, url)
        display_links(links)
        
        # 6. 用户确认
        print("\n" + "="*80)
        print("✨ 分析完成!")
        
        if links:
            print(f"📋 总结: 找到 {len(links)} 个潜在子文档链接")
            
            # 询问用户是否要保存链接到文件
            save_choice = input("\n💾 是否将链接保存到文件? (y/N): ").strip().lower()
            if save_choice in ['y', 'yes']:
                filename = f"extracted_links_{urlparse(url).netloc.replace('.', '_')}.json"
                link_data = {
                    "source_url": url,
                    "extracted_at": asyncio.get_event_loop().time(),
                    "links": [{"text": text, "url": link_url} for text, link_url in links]
                }
                
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(link_data, f, ensure_ascii=False, indent=2)
                
                print(f"✅ 链接已保存到: {filename}")
        else:
            print("⚠️  未找到潜在的子文档链接")
            
        # 询问用户对结果的评价
        print("\n📊 请评价拉取结果:")
        print("1. ✅ 内容完整，包含所需的子URL")
        print("2. ⚠️  内容部分缺失，但包含一些子URL") 
        print("3. ❌ 内容严重缺失，子URL不足")
        print("4. 🔍 需要手动检查HTML")
        
        choice = input("\n请选择 (1-4): ").strip()
        
        feedback_map = {
            "1": "✅ 拉取效果良好",
            "2": "⚠️  拉取效果一般", 
            "3": "❌ 拉取效果不佳",
            "4": "🔍 需要进一步分析"
        }
        
        if choice in feedback_map:
            print(f"\n{feedback_map[choice]}")
            
            if choice == "4":
                # 显示HTML片段供检查
                print("\n🔍 HTML内容片段 (前2000字符):")
                print("-"*50)
                print(html[:2000])
                if len(html) > 2000:
                    print("... (更多内容)")
        
    except Exception as e:
        print(f"❌ 处理URL时发生错误: {e}")
        import traceback
        print("详细错误信息:")
        traceback.print_exc()


async def interactive_mode():
    """交互式模式"""
    print("🚀 Auto Ingest 预览工具 - 交互模式")
    print("="*60)
    print("此工具使用与 auto ingest 相同的方法拉取页面内容")
    print("帮助您确认拉取的内容是否包含所需的子URL")
    print("="*60)
    
    while True:
        print("\n" + "-"*40)
        url = input("🌐 请输入要预览的URL (输入 'quit' 退出): ").strip()
        
        if url.lower() in ['quit', 'exit', 'q']:
            print("👋 再见!")
            break
            
        if not url:
            print("❌ 请输入有效的URL")
            continue
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        await preview_url(url)


def show_help():
    """显示帮助信息"""
    print("""
🚀 Auto Ingest 预览工具
========================

这个脚本使用与 auto ingest 相同的方法拉取页面内容，
并显示拉取结果供人工确认是否包含子 URL。

使用方法:
  python preview_auto_ingest.py <URL>        # 直接分析指定URL
  python preview_auto_ingest.py              # 交互式模式
  python preview_auto_ingest.py --help       # 显示帮助信息

示例:
  python preview_auto_ingest.py https://lmstudio.ai/docs/python
  python preview_auto_ingest.py docs.python.org

功能特性:
  ✅ 使用与 auto ingest 相同的页面拉取方法
  ✅ 显示页面内容预览和HTML结构分析  
  ✅ 自动检测和提取潜在的子文档链接
  ✅ 交互式确认和评价界面
  ✅ 支持将提取的链接保存为JSON文件
""")


async def main():
    """主函数"""
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        # 处理帮助参数
        if arg in ['--help', '-h', 'help']:
            show_help()
            return
            
        # 命令行模式
        url = arg
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        await preview_url(url)
    else:
        # 交互式模式
        await interactive_mode()


if __name__ == "__main__":
    asyncio.run(main())
