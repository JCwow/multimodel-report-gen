# Multimodal Meeting Insights Agent

企業會議分析 Agent：用 **Claude Agent SDK (Python)** 做自主規劃與 Tool Use，經 **MCP Server/Client** 安全接內部目錄、API 與 AWS，可走 **Amazon Bedrock**，並備有 **ECS Fargate** 部署模板、沙箱與自動化 Evals。

上傳會議錄音與簡報截圖後，Agent 自己決定要轉寫、看圖、查歷史會議、對內部員工目錄，還是估雲端成本，最後產出含 Action Items 的 Markdown 報告。

## 對應職缺

| 職缺 | 這個 repo 怎麼證 | 現場可展示 |
| --- | --- | --- |
| 1. Agent 開發 | `app/claude_agent.py`：Claude Agent SDK `query()` loop、`max_turns`、`max_budget_usd`、自訂 MCP tools | `/health` 的 `backend: claude`；報告裡的 `tools_used` |
| 2. MCP 整合 | `mcp_server.py` + `mcp_client.py`：Server 與 Client；Qdrant RAG、內部 API allowlist、S3 prefix | `payroll` deny vs `employees` allow |
| 3. AWS 雲端 | 本機 Bedrock 已跑通；`infra/` 有 Fargate task definition、IAM、CloudFormation、成本估算 | `/health` 的 `bedrock_active: true`；`estimate_aws_cost` |
| 4. 安全與評測 | `app/sandbox.py` 路徑白名單；tool 層 allowlist；`evals/` + `pytest` | `pytest`、`python -m evals.runner` |

LangGraph 三節點（Whisper → Vision → 合成）是 **specialist tools**，不是主迴圈。Claude SDK 不可用時 API 會降級到這條 pipeline，避免 500。

**範圍（面試請照實講）：**

- 內部目錄 / 日曆預設是 fixture；設 `INTERNAL_API_BASE_URL` 才打真實 HTTP。
- Fargate 的 IaC 與 IAM 已寫好，**尚未把服務部署到 ECS 叢集**。本機驗證的是 Bedrock 呼叫與最小權限設計。

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
  ├── lookup_employee / query_internal_api   （employees|calendar|health）
  └── list_meeting_assets / estimate_aws_cost
        │
        ▼
Markdown 報告 + 可選 RAG 索引
```

## 快速開始

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

```json
{
  "status": "healthy",
  "backend": "claude",
  "claude_sdk": true,
  "anthropic_or_bedrock": true,
  "bedrock_active": true
}
```

`bedrock_active` 為 `true` 代表 `.env` 已開 Bedrock，且 boto3 讀得到 AWS 憑證。

```bash
curl -X POST "http://localhost:8742/api/v1/analyze-meeting" \
  -F "audio=@test-meeting.mp3" \
  -F "image1=@test-meeting-ppt.png"
```

### 重啟服務

跑 uvicorn 的終端按 `Ctrl+C`，再執行上面的 `uvicorn` 指令。改 `.env` 或 IAM 之後一定要重啟，健康檢查才會更新。

## MCP Server / Client

stdio server（Cursor / Agent SDK）：

```bash
./run_mcp.sh
```

參考 Client（預設 in-process，不必開 FastAPI）：

```bash
python mcp_client.py list

python mcp_client.py call lookup_employee --args '{"query":"林佳穎"}'
python mcp_client.py call estimate_aws_cost --args '{"vcpu":1,"memory_gb":2}'
```

### MCP deny：payroll 被拒

內部 API 只允許 `employees`、`calendar`、`health`。`payroll` 是刻意用來示範 tool 層 allowlist：模型就算想查薪資也打不出去。

```bash
# 應被拒
python mcp_client.py call query_internal_api --args '{"resource":"payroll","query":"bonus"}'

# 對照：應通過
python mcp_client.py call query_internal_api --args '{"resource":"employees","query":"林佳穎"}'
```

Deny 範例：

```json
{
  "result": "SANDBOX_DENIED: internal API resource not allowlisted: payroll"
}
```

Allow 範例會包含 `E001`、`林佳穎`。實作在 `app/internal_systems.py` 的 `allowed = {"employees", "calendar", "health"}`。

## 沙箱與 Evals

```bash
pytest
python -m evals.runner
```

黃金案覆蓋：路徑逃逸、`.env`、內部 API allowlist（含 payroll）、S3 prefix（只允許 `meetings/`）、報告必填章節、Agent tool trace、Fargate/Bedrock 成本區間。離線就能跑，不依賴 live LLM。

沙箱分三層：

1. 應用層 `app/sandbox.py`：工作目錄白名單、擋 traversal / `.env`、timeout、檔案大小
2. Agent SDK：`tools=[]`，禁用 Bash / Read / Write
3. IAM（上雲時）：task role 只能 `bedrock:InvokeModel` 與 `s3:.../meetings/*`

## Amazon Bedrock（本機）

1. `aws configure` 使用 **IAM user** 的 access key，不要用 root。
2. 區域 `us-east-1`，Bedrock console 需已開啟 Claude 模型。
3. `.env`：

```bash
CLAUDE_CODE_USE_BEDROCK=1
AWS_REGION=us-east-1
AGENT_BACKEND=auto
```

4. 驗證後重啟 uvicorn：

```bash
aws sts get-caller-identity
# Arn 應為 arn:aws:iam::ACCOUNT:user/<name>，不應是 :root

aws bedrock list-foundation-models --region us-east-1 \
  --query "modelSummaries[?contains(modelId, 'claude')].modelId"
```

`CLAUDE_CODE_USE_BEDROCK=1` 但沒有 AWS 憑證時，CLI 會在 initialize 卡住。程式會改走 `ANTHROPIC_API_KEY`；兩者都失敗則降級 pipeline。

建 IAM user、只給 Bedrock 權限、換成該 user 金鑰、再刪 root access key 的步驟見面試準備（最小權限政策名稱建議 `BedrockClaudeInvokeOnly`）。Fargate 部署與成本見 [infra/README.md](infra/README.md)。

## Groq 限額

Whisper / Vision / 合成走 Groq。免費档 OTPM 常為 1000，Vision 預設 `max_tokens` 過高會 429。已預設：

```bash
GROQ_VISION_MAX_TOKENS=512
GROQ_SYNTHESIS_MAX_TOKENS=800
```

若仍 429，等約一分鐘再試，或到 [Groq Billing](https://console.groq.com/settings/billing) 升級。

## API

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| GET | `/health` | 健康檢查與 backend / Bedrock 狀態 |
| POST | `/api/v1/analyze-meeting` | 上傳音訊與最多 3 張圖，產出報告 |
| GET | `/api/v1/search` | Qdrant 搜尋歷史會議 |

`analyze-meeting` 成功時 `data.backend` 為 `claude` 或 `pipeline`。若 Claude SDK 啟動失敗或額度不足，會降級 pipeline 並帶 `data.warning`。

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

## 面試 Demo 順序

1. `GET /health` → `backend: claude`、`bedrock_active: true`
2. `/docs` 上傳短音檔 + 一張有數字的簡報圖 → 結構化報告
3. MCP：`payroll` deny，再對照 `employees` allow
4. `pytest` 或 `python -m evals.runner` 全過
5. 打開 `infra/cloudformation.yaml` 講 Fargate CPU/Memory 與 IAM；用 `estimate_aws_cost` 講成本

開場建議：主迴圈是 Claude Agent SDK 的規劃與 Tool Use，不是寫死 DAG；MCP 是內部系統唯一出口；安全是沙箱 + allowlist + IAM 疊加；Evals 不靠 live LLM 擋迴歸。
