import os
import time
import feedparser
import requests
import json
import hashlib
from datetime import datetime, timedelta
from openai import OpenAI

# ================= 配置区域 =================
# 1. DeepSeek API 配置
# 优先从环境变量获取，如果没有则使用默认值（本地测试用）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-b5a199c465db4b30a2bfd0cff73f4589")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 2. 关键词过滤 (只保留包含这些词的新闻)
KEYWORDS = [
    "GLM", "Kimi", "DeepSeek", "ChatGPT", "Gemini", "Claude", 
    "大模型", "LLM", "GPT-4", "GPT-5", "OpenAI", "Anthropic", "Google DeepMind"
]

# 3. 新闻源 (精选国内外 AI 优质源)
RSS_FEEDS = [
    # --- 国内源 ---
    "https://36kr.com/feed",                # 36氪 (科技综合)
    "https://www.infoq.cn/feed",            # InfoQ (技术深度)
    "https://www.oschina.net/news/rss",     # 开源中国 (国内开源动态)
    "https://rss.huxiu.com/",               # 虎嗅网 (深度商业科技)
    "https://www.qbitai.com/feed",          # 量子位 (AI 垂直媒体，如果 RSS 不可用会自动跳过)
    
    # --- 国外源 (GitHub Actions 可直接访问) ---
    "https://openai.com/blog/rss.xml",      # OpenAI 官方博客
    "https://www.anthropic.com/feed",       # Anthropic (Claude) 官方博客
    "https://googleblog.blogspot.com/feeds/posts/default", # Google AI Blog
    "https://techcrunch.com/category/artificial-intelligence/feed/", # TechCrunch AI
    "https://www.theverge.com/rss/index.xml", # The Verge (前沿科技)
    "https://huggingface.co/blog/feed.xml",   # Hugging Face Blog (开源模型)
]

# 4. 去重记录文件 (GitHub Actions 环境下每次都是新的，主要依赖时间过滤)
HISTORY_FILE = "sent_history.json"

# 5. 日志文件
LOG_FILE = "news_bot.log"

# 6. Server 酱配置 (微信推送)
# 优先从环境变量获取
SERVERCHAN_SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "SCT318073TLLDJl7BzhZ6r1ry5m6sYNvxM")

# ===========================================

def log_message(message):
    """记录日志到文件和控制台"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception as e:
        print(f"写入日志失败: {e}")

def load_sent_history():
    """加载已发送新闻的历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            log_message(f"加载历史记录失败: {e}")
    return set()

def save_sent_history(sent_links):
    """保存已发送新闻的历史记录"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent_links), f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_message(f"保存历史记录失败: {e}")

def get_article_id(link):
    """生成文章唯一ID（基于链接的MD5哈希）"""
    return hashlib.md5(link.encode("utf-8")).hexdigest()

def parse_published_time(entry):
    """解析文章发布时间，返回 datetime 对象或 None"""
    try:
        # 尝试不同的发布时间字段
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            return datetime(*published[:6])
    except Exception:
        pass
    return None

def fetch_news():
    """抓取并筛选新闻"""
    log_message("开始抓取新闻...")
    articles = []
    sent_history = load_sent_history()
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)  # 24小时内的新闻
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            feed_title = feed.feed.get("title", feed_url)
            log_message(f"正在抓取: {feed_title}")
            
            for entry in feed.entries:
                title = entry.title
                link = entry.link
                summary = entry.get("summary", "") + entry.get("description", "")
                
                # 生成文章唯一ID
                article_id = get_article_id(link)
                
                # 检查是否已发送过
                if article_id in sent_history:
                    continue
                
                # 检查发布时间（只看最近24小时的）
                pub_time = parse_published_time(entry)
                if pub_time and pub_time < cutoff_time:
                    continue
                
                # 关键词匹配
                content_to_check = f"{title} {summary}"
                if any(k.lower() in content_to_check.lower() for k in KEYWORDS):
                    articles.append({
                        "id": article_id,
                        "title": title,
                        "link": link,
                        "summary": summary[:200] + "..." if len(summary) > 200 else summary,
                        "published": pub_time.strftime("%Y-%m-%d %H:%M") if pub_time else "未知"
                    })
        except Exception as e:
            log_message(f"抓取 {feed_url} 失败: {e}")
    
    log_message(f"抓取完成，筛选出 {len(articles)} 条新相关新闻。")
    return articles

def summarize_with_deepseek(articles):
    """使用 DeepSeek 总结新闻"""
    if not articles:
        return None

    log_message("正在调用 DeepSeek 进行总结...")
    
    # 构造提示词
    news_text = "\n\n".join([
        f"{i+1}. {a['title']}\n链接: {a['link']}\n发布时间: {a['published']}"
        for i, a in enumerate(articles)
    ])
    
    prompt = f"""以下是过去 24 小时内全球最新的 AI 新闻。请你扮演一位资深 AI 科技编辑，为我生成一份高质量的早报。

要求：
1. **筛选数量**：请从下方列表中筛选出 **10-20 条** 最有价值、最重磅的新闻（如果新闻不够则有多少列多少）。
2. **内容深度**：每条新闻不要只写一句话！请用一段话（约 50-80 字）进行**深度摘要**。
   - 包含：核心事件（What）、技术突破点或关键数据（How）、对行业的影响（Impact）。
   - 如果是国外新闻，必须翻译成流畅的中文。
3. **格式要求**：
   - 标题加粗，前面加序号。
   - 摘要换行显示。
   - 最后附上原文链接。
   - 格式示例：
     **1. OpenAI 发布 GPT-5 预览版**
     摘要：OpenAI 今日突发宣布 GPT-5 预览版，性能在数学和编程基准测试上超越 GPT-4 30% 以上。新模型引入了“慢思考”机制，极大提升了复杂推理能力。这对 Agent 领域将产生深远影响。
     [查看原文](链接)

4. **分类**：请将新闻按类别分组（如：🚀 模型动态、🏢 大厂动向、🔧 开源社区、💡 行业应用）。
5. **热评**：在早报最后，请用一段简短犀利的话（"编辑辣评"），点评今天的整体 AI 趋势。

新闻列表：
{news_text}
"""

    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            timeout=60  # 添加超时设置
        )
        return response.choices[0].message.content
    except Exception as e:
        log_message(f"DeepSeek 调用失败: {e}")
        return None

def split_content(content, limit=3500):
    """
    智能拆分长消息，确保不截断单条新闻
    limit: Server酱限制约 4000 字符，预留 500 字符给标题和统计信息
    """
    if len(content) <= limit:
        return [content]
    
    parts = []
    current_part = ""
    
    # 按新闻条目拆分（假设每条新闻以 **序号. 开头）
    # 使用正则找到每条新闻的起始位置
    import re
    # 匹配 **1. 、**2. 这种格式，或者 ### 标题
    news_items = re.split(r'(?=\*\*\d+\.|### )', content)
    
    for item in news_items:
        if not item.strip():
            continue
            
        # 如果当前部分加上新的一条新闻超过限制，就先保存当前部分
        if len(current_part) + len(item) > limit:
            if current_part:
                parts.append(current_part)
            current_part = item
        else:
            current_part += item
            
    if current_part:
        parts.append(current_part)
        
    return parts

def send_wechat(content, articles=None):
    """使用 Server 酱发送微信消息 (自动拆分长消息)"""
    if not content:
        return False
    
    if not SERVERCHAN_SENDKEY or "SCT" not in SERVERCHAN_SENDKEY:
        log_message("Server 酱 SendKey 未配置，跳过微信推送")
        return False
    
    log_message("正在发送微信消息...")
    
    # 自动拆分消息
    content_parts = split_content(content)
    total_parts = len(content_parts)
    
    success_count = 0
    
    for i, part in enumerate(content_parts):
        try:
            # Server 酱 API 地址
            url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
            
            # 构造标题 (如果是多条，加上序号)
            title = f"🤖 AI 早报 ({datetime.now().strftime('%Y-%m-%d')})"
            if total_parts > 1:
                title += f" [{i+1}/{total_parts}]"
            
            # 构造内容
            desp = part
            # 只在最后一条加上统计信息
            if i == total_parts - 1:
                desp += f"\n\n---\n📊 共 {len(articles) if articles else 0} 条新闻\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            # 发送请求
            data = {
                "title": title,
                "desp": desp
            }
            
            response = requests.post(url, data=data, timeout=30)
            result = response.json()
            
            if result.get("code") == 0:
                log_message(f"第 {i+1}/{total_parts} 条消息发送成功！")
                success_count += 1
            else:
                log_message(f"第 {i+1}/{total_parts} 条消息发送失败: {result.get('message', '未知错误')}")
                
            # 避免发送太快被限制
            if total_parts > 1:
                time.sleep(2)
                
        except Exception as e:
            log_message(f"发送失败: {e}")
    
    return success_count > 0

def job():
    """定时任务执行的主逻辑"""
    log_message("=" * 50)
    log_message("任务开始执行...")
    
    articles = fetch_news()
    if articles:
        summary = summarize_with_deepseek(articles)
        if summary:
            # 只发送微信
            wechat_success = send_wechat(summary, articles)
            
            if wechat_success:
                sent_history = load_sent_history()
                for article in articles:
                    sent_history.add(article["id"])
                save_sent_history(sent_history)
                log_message(f"已记录 {len(articles)} 条新闻到历史记录")
            else:
                log_message("微信发送失败，未记录历史")
        else:
            log_message("摘要生成失败或为空，跳过发送。")
    else:
        log_message("今天没有监测到相关重点新闻。")
    
    log_message("任务执行完成")
    log_message("=" * 50)

def main():
    """主程序入口"""
    log_message("=== AI 新闻助手启动 (GitHub Actions 模式) ===")
    
    # 检查环境变量配置
    if not DEEPSEEK_API_KEY or "sk-" not in DEEPSEEK_API_KEY:
        log_message("错误: 未检测到有效的 DEEPSEEK_API_KEY，请检查 GitHub Secrets 配置。")
        return

    if not SERVERCHAN_SENDKEY or "SCT" not in SERVERCHAN_SENDKEY:
        log_message("警告: 未检测到有效的 Server酱 配置，微信推送可能失败。")

    # 执行一次任务
    try:
        job()
    except Exception as e:
        log_message(f"任务执行出错: {e}")
    
    log_message("=== 任务结束 ===")

if __name__ == "__main__":
    main()
