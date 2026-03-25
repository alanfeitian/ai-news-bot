# AI 新闻机器人

自动抓取 AI 领域新闻，通过 AI 生成摘要，每日推送到微信。

## 功能

- 多源 RSS 聚合（国内外 11 个优质源）
- 关键词智能过滤（OpenAI、DeepSeek、Claude 等）
- DeepSeek AI 生成新闻摘要
- Server酱 推送到微信
- GitHub Actions 每日定时执行
- 历史记录防重复推送

## 部署

### 1. Fork 本仓库

### 2. 配置 GitHub Secrets

进入仓库 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

| Secret 名称 | 说明 | 获取方式 |
|------------|------|---------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | [DeepSeek 开放平台](https://platform.deepseek.com/) |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey | [Server酱官网](https://sct.ftqq.com/) |

### 3. 启用 GitHub Actions

进入 `Actions` 标签页，启用工作流。

默认每天北京时间 08:00 自动执行，也可手动触发。

## 依赖

```
feedparser==6.0.11
requests==2.32.3
openai==1.35.0
```

## 自定义

### 修改新闻源

编辑 `main.py` 中的 `RSS_FEEDS` 列表。

### 修改关键词过滤

编辑 `main.py` 中的 `KEYWORDS` 列表。

### 修改推送时间

编辑 `.github/workflows/daily_news.yml` 中的 `cron` 表达式：

```yaml
schedule:
  - cron: '0 0 * * *'  # UTC 时间，北京时间需 +8
```

## 项目结构

```
ai-news-bot/
├── main.py              # 主程序
├── requirements.txt     # 依赖
├── .github/
│   └── workflows/
│       └── daily_news.yml  # 定时任务
└── sent_history.json    # 已发送记录（自动生成）
```

## License

MIT
