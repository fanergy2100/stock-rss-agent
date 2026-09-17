import feedparser
import requests
import json
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header

# ===================== CONFIG =====================
TARGET_TICKERS = {
    "CNOOC": ["中国海洋石油", "中海油"],
    "Tencent": ["腾讯", "腾讯控股"],
    "PDD": ["拼多多", "PDD"],
    "Xindong": ["心动公司", "心动"],
    "紫金矿业": ["紫金矿业"],
    "Meta": ["Meta", "Facebook"],
    "宁德时代": ["宁德时代"],
    "TSM": ["台积电", "TSMC"],
    "Amazon": ["Amazon", "亚马逊"],
    "Google": ["Google", "Alphabet"]
}
RELEVANCE_THRESHOLD = 6
NOVITA_MODEL = "qwen/qwen-2.5-72b-instruct"

RSS_SOURCES = [
    "https://feeds.bloomberg.com/energy/news.rss",
    "https://seekingalpha.com/tag/china-stocks.xml",
    "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best",
    "https://www.ft.com/rss/companies",
    "https://feeds.marketwatch.com/marketwatch/industrials/",
]

NOVITA_API_KEY = os.getenv("NOVITA_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
TARGET_EMAIL = os.getenv("TARGET_EMAIL")
# ==================================================

def novita_analyze(title, summary):
    prompt = f"""
你是专业投研分析师。
标的列表：{list(TARGET_TICKERS.keys())}
任务：
1. 判断这条新闻和哪个标的相关性，只选**相关性最高的单一标的**；无关返回标的名称：NONE
2. 相关性打分：0~10。10=极强直接影响财报/业务；0=完全无关
3. 简短一句话：新闻情绪（利好/利空/中性）
输出严格JSON，不要多余文字：
{{"ticker":"xxx","score":数字,"sentiment":"xxx"}}
新闻标题：{title}
新闻正文：{summary}
"""
    headers = {"Authorization": f"Bearer {NOVITA_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": NOVITA_MODEL,
        "messages": [{"role":"user","content":prompt}],
        "temperature":0.1
    }
    resp = requests.post("https://api.novita.ai/v3/openai/chat/completions", headers=headers, json=payload, timeout=60)
    res_json = resp.json()
    content = res_json["choices"][0]["message"]["content"].strip()
    return json.loads(content)

def send_email(md_content):
    msg = MIMEText(md_content, "plain", "utf-8")
    msg["Subject"] = Header("【每日投研RSS简报】", "utf-8")
    msg["From"] = GMAIL_USER
    msg["To"] = TARGET_EMAIL
    server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    server.sendmail(GMAIL_USER, TARGET_EMAIL, msg.as_string())
    server.quit()

def main():
    news_pool = []
    seen_link = set()
    for rss_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries[:15]:
                link = entry.get("link","")
                if link in seen_link:
                    continue
                seen_link.add(link)
                title = entry.get("title","")
                summary = entry.get("summary","")
                ai_res = novita_analyze(title, summary)
                ticker = ai_res["ticker"]
                score = int(ai_res["score"])
                sentiment = ai_res["sentiment"]
                if ticker != "NONE" and score >= RELEVANCE_THRESHOLD:
                    news_pool.append({
                        "ticker": ticker,
                        "score": score,
                        "sentiment": sentiment,
                        "title": title,
                        "link": link
                    })
                time.sleep(0.3)
        except Exception as e:
            print(f"RSS源抓取失败 {rss_url} : {e}")

    # 按标的分组
    grouped = {}
    for item in news_pool:
        t = item["ticker"]
        if t not in grouped:
            grouped[t] = []
        grouped[t].append(item)

    # 构建Markdown简报
    md = "# 每日股票RSS资讯简报\n"
    md += f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    for ticker, items in grouped.items():
        md += f"## {ticker}\n"
        for n in items:
            md += f"- 【相关性:{n['score']}｜{n['sentiment']}】[{n['title']}]({n['link']})\n"
        md += "\n"
    if len(news_pool) == 0:
        md += "> 今日没有相关性≥6的资讯\n"
    send_email(md)
    print("✅ 简报邮件发送完成")

if __name__ == "__main__":
    main()
