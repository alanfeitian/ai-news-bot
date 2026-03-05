import os
import time
import feedparser
import requests
import hashlib
import logging
import concurrent.futures
import re
from datetime import datetime, timedelta
from openai import OpenAI

# ================= 配置区域 =================
# 1. DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 2. 关键词过滤 (只保留包含这些词的新闻)
# 使用正则预编译优化匹配速度
KEYWORDS = [
    "DeepSeek", "GPT", "ChatGPT", "OpenAI", "Sora", "o1", "o3",
    "Claude", "Anthropic",
    "Gemini", "Google DeepMind", "DeepMind",
    "GLM", "ChatGLM", "智谱AI",
    "Kimi", "Moonshot", "月之暗面",
    "Llama", "Meta AI",
    "Qwen", "通义千问",
    "Mistral",
    "Grok", "xAI",
    "Doubao", "豆包", "Seed", "Seed-TTS", "Seed-Music", "Seed-Video", "ByteDance", "字节跳动",
    "大模型更新", "模型发布", "新模型", "Model Release", "New Model", "State of the Art", "SOTA"
]
# 编译正则：忽略大小写
KEYWORD_PATTERN = re.compile("|".join(map(re.escape, KEYWORDS)), re.IGNORECASE)

# 3. 新闻源 (精选国内外 AI 优质源)
RSS_FEEDS = [
    # --- 国内源 ---
    "https://36kr.com/feed",                # 36氪 (科技综合)
    "https://www.infoq.cn/feed",            # InfoQ (技术深度)
    "https://www.oschina.net/news/rss",     # 开源中国 (国内开源动态)
    "https://rss.huxiu.com/",               # 虎嗅网 (深度商业科技)
    "https://www.qbitai.com/feed",          # 量子位 (AI 垂直媒体)
    
    # --- 国外源 (GitHub Actions 可直接访问) ---
    "https://openai.com/blog/rss.xml",      # OpenAI 官方博客
    "https://www.anthropic.com/feed",       # Anthropic (Claude) 官方博客
    "https://googleblog.blogspot.com/feeds/posts/default", # Google AI Blog
    "https://techcrunch.com/category/artificial-intelligence/feed/", # TechCrunch AI
    "https://www.theverge.com/rss/index.xml", # The Verge (前沿科技)
    "https://huggingface.co/blog/feed.xml",   # Hugging Face Blog (开源模型)
]

# 4. Server酱配置 (SendKey)
SERVERCHAN_SENDKEY = os.environ.get("SERVERCHAN_SENDKEY")

# 检查必要配置
if not DEEPSEEK_API_KEY:
    raise ValueError("❌ 错误: 环境变量 DEEPSEEK_API_KEY 未设置！请检查 GitHub Secrets。")

if not SERVERCHAN_SENDKEY:
    raise ValueError("❌ 错误: 环境变量 SERVERCHAN_SENDKEY 未设置！请检查 GitHub Secrets。")

# ===========================================

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

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

def fetch_single_feed(feed_url, cutoff_time):
    """抓取单个 RSS 源 (带重试机制)"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 设置 User-Agent 防止被拦截
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # 使用 requests 获取内容，设置超时
            # 部分 RSS 源可能不支持 HEAD 请求或有特殊校验，直接用 GET
            response = requests.get(feed_url, headers=headers, timeout=20)
            
            # 针对 403/404 等错误，不要直接 raise，而是记录并跳过，避免整个程序崩溃
            if response.status_code != 200:
                logger.warning(f"源 {feed_url} 返回状态码 {response.status_code}，跳过")
                return []
            
            # 解析内容
            feed = feedparser.parse(response.content)
            
            # 检查解析是否成功
            if hasattr(feed, 'bozo') and feed.bozo:
                 # 某些源可能有格式错误但仍能解析部分内容，记录警告但不完全失败
                 logger.warning(f"解析 {feed_url} 可能存在格式问题: {feed.bozo_exception}")

            feed_title = feed.feed.get("title", feed_url)
            logger.info(f"正在抓取: {feed_title}")
            
            articles = []
            if not feed.entries:
                 logger.info(f"源 {feed_title} 无内容或解析为空")
                 return []

            for entry in feed.entries:
                title = entry.title
                link = entry.link
                summary = entry.get("summary", "") + entry.get("description", "")
                
                # 检查发布时间（只看最近24小时的）
                # 严厉策略：没有时间的一律丢弃，防止重复抓取旧闻
                pub_time = parse_published_time(entry)
                if not pub_time:
                    # logger.debug(f"丢弃无时间文章: {title}")
                    continue
                
                if pub_time < cutoff_time:
                    continue
                
                # 关键词匹配 (使用正则)
                content_to_check = f"{title} {summary}"
                if KEYWORD_PATTERN.search(content_to_check):
                    articles.append({
                        "id": get_article_id(link),
                        "title": title,
                        "link": link,
                        "summary": summary[:200] + "..." if len(summary) > 200 else summary,
                        "published": pub_time.strftime("%Y-%m-%d %H:%M")
                    })
            return articles
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"网络请求失败 {feed_url} (第 {attempt+1} 次): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
        except Exception as e:
            logger.error(f"抓取 {feed_url} 未知错误: {e}")
            return [] # 非网络错误通常重试也无效，直接返回
            
    logger.error(f"抓取 {feed_url} 最终失败")
    return []

def fetch_news():
    """多线程并发抓取并筛选新闻"""
    logger.info("开始多线程抓取新闻...")
    all_articles = []
    seen_ids = set() # 本次运行去重
    
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)  # 24小时内的新闻
    
    # 限制最大线程数，避免资源耗尽
    max_workers = min(10, len(RSS_FEEDS))
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_url = {executor.submit(fetch_single_feed, url, cutoff_time): url for url in RSS_FEEDS}
        
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                articles = future.result()
                if articles:
                    for article in articles:
                        if article["id"] not in seen_ids:
                            seen_ids.add(article["id"])
                            all_articles.append(article)
            except Exception as e:
                logger.error(f"处理 {url} 结果时出错: {e}")
    
    logger.info(f"抓取完成，共筛选出 {len(all_articles)} 条新相关新闻。")
    return all_articles

def summarize_with_deepseek(articles):
    """使用 DeepSeek 总结新闻 (带重试机制)"""
    if not articles:
        return None

    logger.info("正在调用 DeepSeek 进行总结...")
    
    # 构造提示词
    news_text = "\n\n".join([
        f"{i+1}. {a['title']}\n链接: {a['link']}\n发布时间: {a['published']}"
        for i, a in enumerate(articles)
    ])
    
    prompt = f"""以下是过去 24 小时内全球最新的 AI 新闻。请你扮演一位资深 AI 科技编辑，为我生成一份高质量的早报。

要求：
1. **筛选原则**：
   - **只保留**与核心模型（如 DeepSeek, GPT, Claude, Gemini, GLM, Kimi, Doubao/Seed 等）的**最新版本更新**、发布、重大升级相关的新闻。
   - **自动识别最新版本**：请根据新闻内容，关注当前时间点（{datetime.now().strftime('%Y-%m')}）发布的**最新、最高版本**模型（例如 GPT-5, Claude 4, DeepSeek V4, Seed-Music 2.0 等未来版本），不要局限于旧型号。
   - **过滤掉**：无关的行业融资、普通的 AI 应用、非核心模型的营销软文。
   - 如果没有重大模型更新，就列出这些公司的重要动向。

2. **内容深度**：每条新闻不要只写一句话！请用一段话（约 50-80 字）进行**深度摘要**。
   - 包含：核心事件（What）、技术突破点或关键数据（How）、对行业的影响（Impact）。

3. **格式要求 (严格遵守)**：
   - **强制中文标题**：如果原新闻标题是英文，**必须翻译成中文**。
   - **禁止**使用“各位读者早上好”、“这里是AI早报”等任何开场白或客套话。直接开始列新闻。
   - **禁止**在正文中重复日期（如“今天”、“3月3日”等），因为标题里已经有了。
   - **强制换行**：在标题和摘要之间必须换行。
   - **分割线**：每条新闻之间用 `---` 分割。
   - 格式示例：
     **1. OpenAI 发布 GPT-5 预览版** (如果是英文原标题，这里直接写翻译后的中文)
     
     摘要：OpenAI 今日突发宣布 GPT-5 预览版，性能在数学和编程基准测试上超越 GPT-4 30% 以上。新模型引入了“慢思考”机制，极大提升了复杂推理能力。这对 Agent 领域将产生深远影响。
     [查看原文](链接)
     
     ---

4. **分类**：请将新闻按类别分组（如：🚀 重磅模型更新、🏢 核心大厂动向）。
5. **热评**：在早报最后，请用一段简短犀利的话（"编辑辣评"），点评今天的整体 AI 趋势。

新闻列表：
{news_text}
"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout=90 # 增加超时时间，防止生成长文时中断
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"DeepSeek 调用失败 (第 {attempt+1} 次): {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
            else:
                logger.error("DeepSeek 调用最终失败")
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
    
    # 尝试按分割线 `---` 拆分，这比按序号拆分更稳健
    news_items = content.split('---')
    
    for item in news_items:
        if not item.strip():
            continue
        
        # 补回分割线（除了最后一个片段，显示时美观）
        item_with_separator = item + "\n---\n"
            
        # 如果当前部分加上新的一条新闻超过限制，就先保存当前部分
        if len(current_part) + len(item_with_separator) > limit:
            if current_part:
                parts.append(current_part)
            current_part = item_with_separator
        else:
            current_part += item_with_separator
            
    if current_part:
        parts.append(current_part)
        
    return parts

def send_serverchan(content, articles=None):
    """使用Server酱发送消息 (Markdown)"""
    if not content:
        return False
    
    if not SERVERCHAN_SENDKEY:
        logger.warning("Server酱 SendKey 未配置，跳过推送")
        return False
    
    logger.info("正在发送Server酱消息...")
    
    # Server酱有限制，拆分内容
    content_parts = split_content(content, limit=3500)
    total_parts = len(content_parts)
    
    success_count = 0
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"

    for i, part in enumerate(content_parts):
        try:
            # 构造标题
            title = f"🤖 AI 早报 ({datetime.now().strftime('%Y-%m-%d')})"
            if total_parts > 1:
                title += f" [{i+1}/{total_parts}]"
            
            # 构造内容 (Markdown)
            text = part
            
            # 只在最后一条加上统计信息
            if i == total_parts - 1:
                text += f"\n\n---\n📊 共 {len(articles) if articles else 0} 条新闻\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            payload = {
                "title": title,
                "desp": text
            }
            
            # 发送请求
            for attempt in range(3):
                try:
                    response = requests.post(url, data=payload, timeout=10)
                    result = response.json()
                    
                    if result.get("code") == 0:
                        logger.info(f"第 {i+1}/{total_parts} 条消息发送成功！")
                        success_count += 1
                        break
                    else:
                        logger.warning(f"第 {i+1}/{total_parts} 条消息发送失败: {result.get('message', '未知错误')}")
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Server酱发送网络错误 (第 {attempt+1} 次): {e}")
                    if attempt < 2:
                        time.sleep(2)
                except Exception as e:
                     logger.error(f"Server酱发送未知错误: {e}")
                     break
                
            if total_parts > 1:
                time.sleep(1) # 避免请求过于频繁
                
        except Exception as e:
            logger.error(f"发送流程异常: {e}")
    
    return success_count > 0

def job():
    """定时任务执行的主逻辑"""
    logger.info("=" * 50)
    logger.info("任务开始执行...")
    
    articles = fetch_news()
    if articles:
        summary = summarize_with_deepseek(articles)
        if summary:
            # 发送Server酱
            send_serverchan(summary, articles)
        else:
            logger.warning("摘要生成失败或为空，跳过发送。")
    else:
        logger.info("今天没有监测到相关重点新闻。")
    
    logger.info("任务执行完成")
    logger.info("=" * 50)

def main():
    """主程序入口"""
    logger.info("=== AI 新闻助手启动 (GitHub Actions 模式) ===")
    
    # 打印部分配置信息用于调试 (注意脱敏)
    if SERVERCHAN_SENDKEY:
        masked_sendkey = SERVERCHAN_SENDKEY[:5] + "******" + SERVERCHAN_SENDKEY[-4:] if len(SERVERCHAN_SENDKEY) > 10 else "******"
        logger.info(f"Server酱 SendKey 已配置: {masked_sendkey}")
    else:
        logger.error("Server酱 SendKey 未找到！")

    # 执行一次任务
    try:
        job()
    except Exception as e:
        logger.error(f"任务执行出错: {e}")
        # 在 Actions 中抛出异常，标记为失败
        raise e
    
    logger.info("=== 任务结束 ===")

if __name__ == "__main__":
    main()
