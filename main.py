import feedparser
import requests
import json
import time
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
import os

# ========== 配置区 ==========
# 目标标的列表
TARGET_STOCKS = [
    "中国海洋石油", "腾讯", "心动公司", "PDD",
    "Meta", "宁德时代", "Google", "TSM", "紫金矿业", "Amazon"
]
RELEVANCE_THRESHOLD = 6  # 相关性阈值 >=6才保留

# Novita API
NOVITA_API_KEY = os.getenv("NOVITA_API_KEY")
MODEL_NAME = "qwen/qwen-2.5-72b-instruct"
API_URL = "https://api.novita.ai/v3/openai/chat/completions"

# Gmail 邮件配置
MAIL_USER = os.getenv("GMAIL_USER")
MAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
TARGET_EMAIL = os.getenv("TARGET_EMAIL")

# RSS源列表，已移除失效FT源，新增稳定港股/中概源
RSS_FEEDS = [
    "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best&topic=china",
    "https://www.scmp.com/rss/2/feed",
    "https://feeds.seekingalpha.com/tags/china-stocks.xml",
    "https://www.aastocks.com/en/stock/rss/newsrss.xml",
    "https://www.cnbc.com/id/10000104/device/rss/rss.xml",
    "https://www.caixinglobal.com/feed/"
]

# 本地缓存，用于新闻去重
seen_links = set()
# ============================

def call_llm_analysis(title, summary):
    """调用Novita大模型，返回：匹配标的、相关性分数、情绪、原文摘要"""
    sys_prompt = f"""
你是专业港股/美股投研分析师。
标的列表：{TARGET_STOCKS}
任务：分析这篇新闻标题+摘要。输出严格JSON，不要额外文字。
输出字段：
1. matched_stock：只返回【相关性最高的单个标的名称】，无匹配填null
2. relevance_score：0~10整数，10=极强相关
3. sentiment：positive / neutral / negative
4. brief_summary：中文简短摘要，50字以内

规则：
- 只选一个最相关标的；无关则matched_stock=null，分数0
- 相关性≥6才属于有效资讯
"""
    user_content = f"标题：{title}\n摘要：{summary}"
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2
    }
    headers = {
        "Authorization": f"Bearer {NOVITA_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        # 清洗markdown代码块
        if raw.startswith("```json"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"AI分析失败: {str(e)}")
        return None

def fetch_rss(feed_url):
    print(f"\n【源】{feed_url}")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        res = requests.get(feed_url, timeout=15, headers=headers)
        feed = feedparser.parse(res.text)
        entries = feed.entries
        print(f"共{len(entries)}条资讯")
        return entries
    except Exception as e:
        print(f"⚠️ 该源抓取失败：{str(e)}")
        return []

def send_email(markdown_content):
    msg = MIMEText(markdown_content, "plain", "utf-8")
    msg["Subject"] = "【每日投研RSS简报】"
    msg["From"] = MAIL_USER
    msg["To"] = TARGET_EMAIL
    msg["Date"] = formatdate(localtime=True)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(MAIL_USER, MAIL_PASS)
        smtp.send_message(msg)
    print("✅ 简报邮件发送完成")

def main():
    stock_group = {}
    # 初始化分组
    for s in TARGET_STOCKS:
        stock_group[s] = []

    for feed_url in RSS_FEEDS:
        entries = fetch_rss(feed_url)
        for entry in entries:
            link = entry.get("link", "")
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            ai_result = call_llm_analysis(title, summary)
            time.sleep(0.3)
            if not ai_result:
                continue
            match_stock = ai_result.get("matched_stock")
            score = ai_result.get("relevance_score", 0)
            if match_stock is None or score < RELEVANCE_THRESHOLD:
                continue
            # 存入对应标的分组
            stock_group[match_stock].append({
                "title": title,
                "link": link,
                "score": score,
                "sentiment": ai_result["sentiment"],
                "summary": ai_result["brief_summary"]
            })

    # 生成Markdown简报
    md_lines = []
    md_lines.append("# 每日股票RSS资讯简报")
    md_lines.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    has_news = False
    for stock_name, news_list in stock_group.items():
        if len(news_list) == 0:
            continue
        has_news = True
        md_lines.append(f"\n## {stock_name}")
        # 按相关性分数降序排序
        news_list.sort(key=lambda x:x["score"], reverse=True)
        for news in news_list:
            md_lines.append(f"- 【相关性:{news['score']} | {news['sentiment']}】[{news['title']}]({news['link']})")
            md_lines.append(f"  > {news['summary']}")
    if not has_news:
        md_lines.append(f"\n> 今日没有相关性≥{RELEVANCE_THRESHOLD}的资讯")
    final_md = "\n".join(md_lines)
    send_email(final_md)

if __name__ == "__main__":
    main()
