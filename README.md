# Multimodal Meeting Insights Agent

結合 Whisper 語音轉寫、GPT-4o Vision 圖像分析與 LangGraph 狀態圖的多模態會議分析服務。上傳會議錄音與簡報截圖，自動產出結構化 Markdown 會議報告。

## 架構與資料流

```
客戶端上傳 (.mp3/.wav + .png/.jpg)
        │
        ▼
FastAPI 異步 Endpoint
        │
        ▼
LangGraph Agent Pipeline
  ├── Speech Node (Whisper)     → 逐字稿
  ├── Vision Node (GPT-4o)      → 圖表數據與關鍵字
  └── Synthesizer Node (LLM)    → Markdown 會議報告
```

## 快速開始

### 1. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env，填入你的 OPENAI_API_KEY
export OPENAI_API_KEY=sk-...
```

### 2. 本地執行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8742 --reload
```

開啟 API 文件：http://localhost:8742/docs

### 3. Docker 一鍵部署

```bash
docker build -t multimodal-insights-agent .
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... multimodal-insights-agent
```

## API 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/health` | 健康檢查 |
| POST | `/api/v1/analyze-meeting` | 上傳音訊與圖片，產出會議報告 |

### 分析會議範例

使用 `curl` 上傳檔案：

```bash
curl -X POST "http://localhost:8742/api/v1/analyze-meeting" \
  -F "audio=@meeting.mp3" \
  -F "images=@slide1.png"
```

回應格式：

```json
{
  "status": "success",
  "data": {
    "transcript": "會議逐字稿...",
    "image_insights": ["圖片分析結果..."],
    "report": "# 會議摘要報告\n..."
  }
}
```

## 專案結構

```
multimodal-insights-agent/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI 進入點與 RESTful API
│   └── agent.py           # LangGraph Agent 狀態圖與 Prompt 邏輯
├── Dockerfile             # Docker 部署（含 ffmpeg）
├── requirements.txt       # Python 依賴
└── README.md
```

## 面試展示建議

1. 啟動服務後開啟 `/docs` 介面
2. 上傳 15–30 秒錄音 + 1 張含圖表的投影片
3. 展示自動產出的 Markdown 結構化報告

### 架構亮點

- **多模態 Pipeline**：LangGraph `AgentState` 管理語音與影像的流水線處理
- **結構化輸出**：LLM 交叉比對逐字稿與簡報數據，產出決策與 Action Items
- **容器化**：Docker 封裝 ffmpeg 等系統依賴，支援一鍵部署

### 擴展方向

- 長音訊 / 高併發：引入 Celery + Redis 改為異步佇列
- 成本優化：對圖片做 Perception Hash 去重，降低 Vision API 費用

## 授權

MIT
