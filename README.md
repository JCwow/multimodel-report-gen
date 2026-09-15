# Multimodal Meeting Insights Agent

上傳會議錄音與簡報截圖後，Agent 自己決定要轉寫、看圖、查歷史會議、對內部員工目錄，還是估雲端成本，最後產出含 Action Items 的 Markdown 報告。

主迴圈是 **Claude Agent SDK** 的規劃與 Tool Use（不是寫死 DAG）。Claude 路徑經 **MCP** 接內部系統；可走 **Amazon Bedrock**，並附 **ECS Fargate** 模板、沙箱與離線 Evals。

## 核心架構

```
客戶端上傳  test-meeting.mp3 + test-meeting-ppt.png
        │
        ▼
FastAPI  /api/v1/analyze-meeting
        │  寫入 sandbox_workspace/jobs/<id>/
        ▼
Claude Agent SDK  （規劃 / 多步 Tool Use / max_turns / max_budget_usd）
        │  內建 Bash/Read/Write 已關掉，只准 MCP tools
        ▼
MCP tools（依功能走 sandbox、allowlist 或 IAM）
  ├── transcribe_audio / analyze_slides / synthesize_report
  ├── analyze_meeting_files          （一次跑完整音訊 + 圖片 + 報告）
  ├── query_historical_meetings      → Qdrant
  ├── lookup_employee / query_internal_api   （employees | calendar | health）
  └── list_meeting_assets / estimate_aws_cost
        │
        ▼
Markdown 報告 + tools_used  → 可選寫入 Qdrant

SDK 啟動、認證、連線或額度失敗時 → LangGraph pipeline（Whisper → Vision → 合成）
```

LangGraph 三節點是 specialist tools，不是主迴圈。Claude 路徑只准 MCP；API 僅在 SDK 啟動 / 認證 / 連線 / 額度失敗時降級（仍要 Groq）。

## 快速開始

Python 3.11+。Claude Agent SDK 會呼叫 bundled Claude Code CLI；本機若 CLI initialize 卡住，多半是開了 Bedrock 卻沒有 AWS 憑證。

```bash
cp .env.example .env
# 必填 GROQ_API_KEY（語音 / 視覺 / 合成）
# 走 Claude Agent SDK：ANTHROPIC_API_KEY，或 CLAUDE_CODE_USE_BEDROCK=1 + aws configure

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d qdrant
uvicorn app.main:app --host 0.0.0.0 --port 8742 --reload
```

- API 文件：http://localhost:8742/docs
- 健康檢查：http://localhost:8742/health
- 改 `.env` 或 IAM 後需重啟 uvicorn，健康檢查才會更新。

新鮮 clone、只填 `GROQ_API_KEY` 時，`bedrock_active` 為 `false`；沒有 Anthropic / Bedrock 憑證則 `backend` 為 `pipeline`：

```json
{
  "status": "healthy",
  "service": "Multimodal Agent API",
  "backend": "pipeline",
  "claude_sdk": true,
  "anthropic_or_bedrock": false,
  "bedrock_active": false
}
```

已設 `ANTHROPIC_API_KEY` 時 `backend` 為 `claude`，`bedrock_active` 仍是 `false`。只有 `.env` 開了 Bedrock **且** boto3 讀得到 AWS credentials，才會是 `bedrock_active: true`。

Repo 內已有測試檔：`test-meeting.mp3`，以及簡報圖 `test-meeting-ppt.png`（2026 Q2：線上 +25.4% / $12.5M，門市 -11.2% / $4.2M）。

```bash
curl -X POST "http://localhost:8742/api/v1/analyze-meeting" \
  -F "audio=@test-meeting.mp3" \
  -F "image1=@test-meeting-ppt.png"
```

成功時 HTTP 200，重點欄位如下（`report` 會更長；`tools_used` 隨 Agent 規劃而變）：

```json
{
  "status": "success",
  "data": {
    "transcript": "……逐字稿……",
    "image_insights": ["線上電商 +25.4%，實體門市 -11.2% ……"],
    "report": "# 會議核心主題與目標\n……\n## 關鍵決策與 Action Items\n……",
    "tools_used": ["transcribe_audio", "analyze_slides", "lookup_employee"],
    "backend": "claude",
    "warning": null
  }
}
```

若 Claude SDK 啟動失敗或額度不足，同一支 API 會降級：`data.backend` 為 `"pipeline"`，並帶 `data.warning`。報告經 response 回傳，可索引至 Qdrant；不保證寫成固定檔名 `report.md`。

## MCP Server / Client

預設 `MCP_TRANSPORT=sdk`（in-process）。stdio server（Cursor / 對照 Agent SDK）：

```bash
./run_mcp.sh
```

參考 Client（預設 in-process，不必開 FastAPI）：

```bash
python mcp_client.py list
python mcp_client.py call lookup_employee --args '{"query":"林佳穎"}'
python mcp_client.py call estimate_aws_cost --args '{"vcpu":1,"memory_gb":2}'
```

內部 API 只允許 `employees`、`calendar`、`health`。`payroll` 是刻意用來示範 tool 層 allowlist：模型就算想查薪資也打不出去。

```bash
# 應被拒
python mcp_client.py call query_internal_api --args '{"resource":"payroll","query":"bonus"}'

# 對照：應通過，結果含 E001 / 林佳穎
python mcp_client.py call query_internal_api --args '{"resource":"employees","query":"林佳穎"}'
```

Deny 範例：`{"result": "SANDBOX_DENIED: internal API resource not allowlisted: payroll"}`。實作在 `app/internal_systems.py`。

| 工具 | 用途 | 主要限制 |
| --- | --- | --- |
| `transcribe_audio` | 沙箱內音訊 → Groq Whisper | 只讀沙箱內允許的音訊格式 |
| `analyze_slides` | 分析簡報 / 白板圖 | 只讀沙箱內 `.png` / `.jpg` / `.jpeg` |
| `synthesize_report` | 逐字稿 + 圖片洞察 → Markdown | 走受控 specialist |
| `analyze_meeting_files` | 一次跑完音訊、圖片與報告 | 輸入仍經沙箱檢查 |
| `query_historical_meetings` | Qdrant 搜歷史會議 | Qdrant 離線可回空結果 |
| `lookup_employee` | 查內部員工目錄 | 預設 fixture；可接內部 API |
| `query_internal_api` | 查員工、日曆或 health | allowlist：`employees`、`calendar`、`health` |
| `list_meeting_assets` | 列出會議資產 | 僅 `meetings/` S3 prefix 或本地 fixture |
| `estimate_aws_cost` | 估 Fargate / Bedrock 月成本 | 只估算，不建立或修改 AWS 資源 |

## 沙箱與 Evals

```bash
pytest
python -m evals.runner
```

黃金案覆蓋路徑逃逸、`.env`、內部 API allowlist（含 payroll）、S3 prefix（只允許 `meetings/`）、報告必填章節、Agent tool trace、Fargate/Bedrock 成本區間。離線就能跑，不依賴 live LLM。

安全分三層，疊加而不是互相替代：

1. 應用層 `app/sandbox.py`：工作目錄白名單、擋 traversal / `.env`、timeout、檔案大小（管檔案類工具）
2. Agent SDK：`tools=[]`，`disallowed_tools` 含 Bash / Read / Write，`allowed_tools` 只放 MCP
3. IAM（上雲時）：task role 只能 `bedrock:InvokeModel` 與 `s3:.../meetings/*`

目錄、日曆、成本估算走 allowlist / fixture，不是檔案沙箱。

## Amazon Bedrock（本機）

1. `aws configure` 使用 **IAM user** 的 access key，不要用 root。
2. 區域 `us-east-1`，Bedrock console 需已開啟 Claude 模型。
3. `.env`：`CLAUDE_CODE_USE_BEDROCK=1`、`AWS_REGION=us-east-1`、`AGENT_BACKEND=auto`
4. 重啟 uvicorn 後：`aws sts get-caller-identity`（Arn 不應是 `:root`），再用 `aws bedrock list-foundation-models` 確認 Claude 模型。沒有 AWS 憑證時改走 `ANTHROPIC_API_KEY`，兩者都失敗則降級 pipeline。

Fargate 部署與成本見 [infra/README.md](infra/README.md)。

## API

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| GET | `/health` | backend / Bedrock 狀態 |
| POST | `/api/v1/analyze-meeting` | 上傳音訊與最多 3 張圖，產出報告 |
| GET | `/api/v1/search` | Qdrant 搜尋歷史會議 |

## 目前限制

- 內部員工目錄與日曆預設是本地 fixture；設 `INTERNAL_API_BASE_URL` 才打真實 HTTP。
- Qdrant 需先啟動（`docker compose up -d qdrant`）。歷史搜尋不依賴 live LLM，向量服務不可用時功能會受限。
- Groq Whisper / Vision / 合成需要 `GROQ_API_KEY`。免費檔 OTPM 常為 1000；預設 `GROQ_VISION_MAX_TOKENS=512`、`GROQ_SYNTHESIS_MAX_TOKENS=800`，仍 429 就等一分鐘或升級 [Groq Billing](https://console.groq.com/settings/billing)。
- Claude Agent SDK 需要 `ANTHROPIC_API_KEY`，或 `CLAUDE_CODE_USE_BEDROCK=1` 加上可用的 AWS credentials。
- Fallback 只涵蓋 `is_sdk_startup_error`（啟動、認證、連線、額度），不是所有執行期錯誤都能自動恢復。
- `infra/` 有 ECS Fargate、CloudFormation 與 IAM 模板，**尚未把服務部署到 ECS 叢集**。本機驗證的是 Bedrock 呼叫與最小權限設計。
- Agent 主迴圈受 `AGENT_MAX_TURNS` 與 `AGENT_MAX_BUDGET_USD` 限制。

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
tests/                 pytest
```

## 面試準備

| 職缺 | 這個 repo 怎麼證 | 現場可展示 |
| --- | --- | --- |
| 1. Agent 開發 | `app/claude_agent.py`：SDK `query()` loop、`max_turns`、`max_budget_usd`、自訂 MCP tools | `/health` 的 `backend: claude`；報告裡的 `tools_used` |
| 2. MCP 整合 | `mcp_server.py` + `mcp_client.py`；Qdrant RAG、內部 API allowlist、S3 prefix | `payroll` deny vs `employees` allow |
| 3. AWS 雲端 | 支援本機 Bedrock 驗證；`infra/` 有 Fargate task definition、IAM、CloudFormation、成本估算 | `/health` 的 `bedrock_active: true`；`estimate_aws_cost` |
| 4. 安全與評測 | `app/sandbox.py` 路徑白名單；tool 層 allowlist；`evals/` + `pytest` | `pytest`、`python -m evals.runner` |

**Demo 順序**

1. `GET /health` → 有金鑰時 `backend: claude`；有 Bedrock 時 `bedrock_active: true`
2. `/docs` 上傳 `test-meeting.mp3` + `test-meeting-ppt.png` → 結構化報告（對照 +25.4% / -11.2%）
3. MCP：`payroll` deny，再對照 `employees` allow
4. `pytest` 或 `python -m evals.runner` 全過
5. 打開 `infra/cloudformation.yaml` 講 Fargate CPU/Memory 與 IAM；用 `estimate_aws_cost` 講成本 
```bash
# 成本 Demo 指令：
python mcp_client.py call estimate_aws_cost \
  --args '{"vcpu":1,"memory_gb":2}'
# 輸出中的:
"total_usd": 48.04
```


**開場：** 主迴圈是 Claude Agent SDK 的規劃與 Tool Use，不是寫死 DAG；Claude 路徑上 MCP 是內部系統唯一出口；安全是沙箱 + allowlist + IAM 疊加；Evals 不靠 live LLM 擋迴歸。內部目錄預設 fixture、Fargate 尚未部署到叢集——請照實講。
