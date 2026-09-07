# Multimodal Meeting Insights Agent

企業會議分析 Agent：用 **Claude Agent SDK** 做自主規劃與 Tool Use，經 **MCP** 安全接內部目錄 / API / AWS，部署到 **ECS Fargate + Amazon Bedrock**，並以沙箱 + 自動化 Evals 守住執行邏輯。

上傳會議錄音與簡報截圖後，Agent 自己決定要轉寫、看圖、查歷史會議、對內部員工目錄，還是估 AWS 成本，最後產出結構化 Markdown 報告。

## 對應職缺的四塊

| 職缺 | 這個 repo 怎麼證 |
| --- | --- |
| 1. Agent 開發 | `app/claude_agent.py`：Claude Agent SDK `query()` loop、`max_turns`、自訂 MCP tools |
| 2. MCP 整合 | `mcp_server.py` + `mcp_client.py`：Server/Client，接 Qdrant、內部 API、S3 prefix |
| 3. AWS 部署 | `infra/`：Fargate task definition、IAM、CloudFormation、Bedrock、成本估算 |
| 4. 安全與評測 | `app/sandbox.py` 路徑白名單；`evals/runner.py` + `pytest` 黃金案 |

LangGraph 三節點（Whisper → Vision → 合成）仍在，但已降成 **specialist tools**，不再是主迴圈。沒有 Anthropic / Bedrock 金鑰時，API 會自動退回這條 pipeline，方便本機 demo。

```
客戶端上傳 (.mp3/.wav + .png/.jpg)
        │
        ▼
FastAPI  → 寫入 sandbox_workspace/jobs/<id>/
        │
        ▼
Claude Agent SDK  (規劃 / 多步 Tool Use / max_budget_usd)
        │  MCP client
        ▼
MCP Server tools（全部過 sandbox）
  ├── transcribe_audio / analyze_slides / synthesize_report
  ├── query_historical_meetings   → Qdrant
  ├── lookup_employee / query_internal_api
  └── list_meeting_assets / estimate_aws_cost
        │
        ▼
Markdown 報告 + 可選 RAG 索引
```

## 快速開始

```bash
cp .env.example .env
# 填 GROQ_API_KEY；若要走 Claude Agent SDK 再填 ANTHROPIC_API_KEY
# 或 CLAUDE_CODE_USE_BEDROCK=1 並設定 AWS 憑證

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d qdrant
uvicorn app.main:app --host 0.0.0.0 --port 8742 --reload
```

- API 文件：http://localhost:8742/docs
- 健康檢查會回傳目前 backend（`claude` 或 `pipeline`）

```bash
curl -X POST "http://localhost:8742/api/v1/analyze-meeting" \
  -F "audio=@test-meeting.mp3" \
  -F "image1=@test-meeting-ppt.png"
```

### MCP Server / Client

```bash
# Cursor / Claude Agent SDK 用 stdio server
./run_mcp.sh

# 參考 Client（in-process）
python mcp_client.py list
python mcp_client.py call lookup_employee --args '{"query":"林佳穎"}'
python mcp_client.py call estimate_aws_cost --args '{"vcpu":1,"memory_gb":2}'
```

### 沙箱與 Evals

```bash
pytest
python -m evals.runner
```

黃金案覆蓋：路徑逃逸、`.env`、內部 API allowlist、S3 prefix、報告必填章節、Agent tool trace、Fargate/Bedrock 成本區間。

## 專案結構

```
app/
  claude_agent.py      Claude Agent SDK 編排
  sandbox.py           路徑白名單 / timeout / 檔案大小
  tools.py             MCP 與 SDK 共用的 tool 實作
  internal_systems.py  內部目錄、API allowlist、AWS 適配
  agent.py             LangGraph specialists（語音 / 視覺 / 合成）
  main.py              FastAPI
mcp_server.py          MCP Server（stdio）
mcp_client.py          MCP Client
evals/                 黃金案與 runner
infra/                 Fargate / IAM / Bedrock / 成本
```

## AWS

見 [infra/README.md](infra/README.md)。重點：

- 容器含 Python 3.11 + Node.js 20 + `@anthropic-ai/claude-code`（Agent SDK 會 spawn CLI）
- `CLAUDE_CODE_USE_BEDROCK=1`，task role 只允許 `bedrock:InvokeModel`
- S3 只開 `meetings/*` prefix
- `AGENT_MAX_TURNS` / `AGENT_MAX_BUDGET_USD` 卡住單次 run 成本
- 1 vCPU / 2 GB 常駐約 USD $36/月 Fargate + Bedrock token；Haiku / scale-to-zero / Graviton 可再往下壓

## 面試時建議怎麼講

1. 主迴圈是 Claude Agent SDK，不是寫死 DAG；模型自己選 tool、可多步。
2. MCP Server 是唯一能碰內部系統的邊界；Client 在 SDK 與 `mcp_client.py` 兩邊都有。
3. 安全是疊加的：應用沙箱 + 禁用 Bash/Read/Write + IAM least privilege。
4. Evals 不依賴 live LLM：golden cases 在 CI 就能擋迴歸；有金鑰再補 live trace。
