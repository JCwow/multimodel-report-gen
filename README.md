# Multimodal Meeting Insights Agent

上傳會議錄音與簡報截圖後，Agent 自己決定要轉寫、看圖、查歷史會議、對內部員工目錄，還是估雲端成本，最後產出含 Action Items 的 Markdown 報告。

主迴圈是 **Claude Agent SDK** 的規劃與 Tool Use（不是寫死 DAG）。Claude 路徑經 **MCP** 接內部系統；可走 **Amazon Bedrock**，並附 **ECS Fargate** 模板、沙箱與離線 Evals。

> 執行模式要分清楚：`backend: "claude"` 才會執行 Claude Agent SDK 與 MCP 的自主工具規劃；`backend: "pipeline"` 則執行固定的 LangGraph 三節點 fallback（轉寫 → 視覺 → 報告）。兩者都會產出同一份 API response，但 `tools_used` 的名稱與自主性不同。

## 已驗證範圍與部署狀態

| 項目 | 狀態 | 說明 |
| --- | --- | --- |
| 本機 FastAPI / Docker Compose | 可執行 | Qdrant 與 Agent 可由 Docker Compose 啟動；模型呼叫仍需有效的 provider key。 |
| Claude Agent SDK + MCP | 可在相容 runtime 驗證 | 需 Anthropic API key 或可用 Bedrock credentials；不是所有 container CPU 架構都相容 bundled CLI。 |
| LangGraph pipeline | 已在本機 kind 成功執行 | 音訊、投影片與報告三步皆實際跑過；回應會是 `backend: "pipeline"`。 |
| Kubernetes manifests | 已提供；kind demo 已驗證 | 使用 ClusterIP、兩個 API replicas、Qdrant、probes、資源限制與 HPA manifest。詳見 [infra/k8s/README.md](infra/k8s/README.md)。 |
| ECS Fargate / Bedrock | IaC 與設定已提供 | 尚未宣稱部署到 production ECS cluster；部署前要提供可達的 Qdrant endpoint、Groq secret ARN、VPC/subnet 與模型存取權。 |

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
  "claude_sdk": false,
  "claude_sdk_checked": false,
  "anthropic_or_bedrock": false,
  "bedrock_active": false
}
```

`AGENT_BACKEND=pipeline` 時，健康檢查刻意不 import optional Claude SDK，並回傳 `claude_sdk_checked: false`，避免 Kubernetes probe 因不相容 SDK/CLI 而失敗。已設 `ANTHROPIC_API_KEY` 且 `AGENT_BACKEND=auto` 時，`backend` 為 `claude`，`bedrock_active` 仍是 `false`。只有 `.env` 開了 Bedrock **且** boto3 讀得到 AWS credentials，才會是 `bedrock_active: true`。

Repo 內已有測試檔：`test-meeting.mp3`，以及簡報圖 `test-meeting-ppt.png`（2026 Q2：線上 +25.4% / $12.5M，門市 -11.2% / $4.2M）。

```bash
curl -X POST "http://localhost:8742/api/v1/analyze-meeting" \
  -F "audio=@test-meeting.mp3" \
  -F "image1=@test-meeting-ppt.png"
```

成功時 HTTP 200，重點欄位如下（`report` 會更長）。Claude 路徑的 `tools_used` 隨 Agent 規劃而變；pipeline 路徑固定回傳 `speech_processor`、`vision_processor`、`synthesizer`：

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

若 `AGENT_BACKEND=auto` 的 Claude SDK 發生啟動、認證、CLI 連線或 credit-balance 類錯誤，同一支 API 可降級：`data.backend` 為 `"pipeline"`，並帶 `data.warning`。`AGENT_BACKEND=pipeline` 則直接走 pipeline，`warning` 會是 `null`。報告只經 response 回傳，並可索引至 Qdrant；不保證寫成固定檔名 `report.md`。

## 設定參考

完整的可複製範本在 [.env.example](.env.example)。以下是會直接影響 runtime 的設定：

| 變數 | 預設值 | 作用 |
| --- | --- | --- |
| `GROQ_API_KEY` | 無 | 語音、視覺、報告 specialist 的必要 key。 |
| `GROQ_VISION_MODEL` | `qwen/qwen3.6-27b`（程式） | 視覺模型；Kubernetes ConfigMap 明確設為 `qwen/qwen3.8-27b`。請以該 key 的 `/models` 清單確認可用性。 |
| `GROQ_VISION_MAX_TOKENS` / `GROQ_SYNTHESIS_MAX_TOKENS` | `512` / `800` | 各 specialist 的輸出 token 上限。 |
| `GROQ_SYNTHESIS_MODEL` | `openai/gpt-oss-120b` | 報告生成模型。 |
| `AGENT_BACKEND` | `auto` | `auto`：有 Claude/Bedrock credentials 才選 Claude；`claude`：強制 SDK；`pipeline`：固定 LangGraph workflow。 |
| `AGENT_MAX_TURNS` / `AGENT_MAX_BUDGET_USD` | `12` / `0.50` | Claude Agent SDK 的回合與預算硬上限；不影響 pipeline。 |
| `MCP_TRANSPORT` | `sdk` | `sdk` 為 process 內 MCP server；`stdio` 會以 `mcp_server.py` 啟動 server。 |
| `QDRANT_HOST` / `QDRANT_PORT` | `localhost` / `6333` | Qdrant 連線位置；無法連線時索引跳過，搜尋回空結果。 |
| `SANDBOX_ROOT` / `MAX_FILE_BYTES` / `TOOL_TIMEOUT_SEC` | `./sandbox_workspace` / 25 MiB / 120 秒 | 上傳與檔案型工具的安全邊界。 |
| `CLAUDE_CODE_USE_BEDROCK` / `AWS_REGION` | `0` / `us-east-1` | 設為 Bedrock 並可取得 AWS credentials 時，Claude SDK 使用 Bedrock。 |
| `AWS_MEETING_BUCKET` / `AWS_MEETING_PREFIX` | 空 / `meetings/` | 啟用 live S3 listing；空 bucket 時回傳 fixture。 |
| `INTERNAL_API_BASE_URL` | 空 | 啟用 live 內部 HTTP API；空值時使用 deterministic fixtures。 |

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

## Kubernetes：本機 kind 與 GKE manifests

Kubernetes manifests 位於 [`infra/k8s/`](infra/k8s/)。它們部署 FastAPI API 與其 temporary sandbox；**不會**部署 Qdrant，因此 cluster 內必須另有名為 `qdrant`、port `6333` 的 Service，或調整 `QDRANT_HOST`。

### 已驗證的 kind demo

此路徑使用 Docker Desktop + kind，不產生雲端 Kubernetes 費用。它使用 `configmap.kind.yaml` 強制 `AGENT_BACKEND=pipeline`，原因是本專案的 Claude Agent SDK / bundled CLI 在部分 Kubernetes-in-Docker CPU 架構會以 exit code 132 (`SIGILL`) 結束；這是 runtime compatibility 限制，不是 MCP 或 Qdrant 問題。

```bash
# 先確定 Docker Desktop 已啟動，且已安裝 kind、kubectl
kind create cluster --name meeting-demo

docker build -t meeting-insights-agent:local .
kind load docker-image meeting-insights-agent:local --name meeting-demo

kubectl create namespace meeting-insights
kubectl -n meeting-insights create deployment qdrant --image=qdrant/qdrant:latest
kubectl -n meeting-insights expose deployment qdrant --port=6333 --target-port=6333
kubectl -n meeting-insights rollout status deployment/qdrant

kubectl -n meeting-insights create secret generic meeting-insights-agent-secrets \
  --from-literal=GROQ_API_KEY='replace-me'

kubectl -n meeting-insights apply -f infra/k8s/serviceaccount.yaml
kubectl -n meeting-insights apply -f infra/k8s/configmap.yaml
kubectl -n meeting-insights apply -f infra/k8s/configmap.kind.yaml
kubectl -n meeting-insights apply -f infra/k8s/deployment.yaml
kubectl -n meeting-insights apply -f infra/k8s/service.yaml
kubectl -n meeting-insights rollout status deployment/meeting-insights-agent
kubectl -n meeting-insights get pods,svc
```

`deployment.yaml` 目前將 image 設為 `meeting-insights-agent:local`，適合上述 kind demo。部署 GKE 或其他 registry 前，請把它改成 immutable image digest；完整的 production-shaped checklist、HPA、Secret 與 Workload Identity 說明在 [infra/k8s/README.md](infra/k8s/README.md)。

以 port-forward 測試時保持第一個 terminal 不關閉；如果 `8742` 被本機 uvicorn 佔用，可以改用 `8743`：

```bash
kubectl -n meeting-insights port-forward service/meeting-insights-agent 8743:80
# 新 terminal
curl http://127.0.0.1:8743/health
```

成功的 kind health response 應為 `backend: "pipeline"` 與 `claude_sdk_checked: false`。接著開 `http://127.0.0.1:8743/docs`，上傳 `test-meeting.mp3` 和 `test-meeting-ppt.png`。範例的 Groq key 必須可用 `whisper-large-v3`、`qwen/qwen3.8-27b` 及 `openai/gpt-oss-120b`；可用模型因帳號／方案不同，先用下列命令查詢：

```bash
kubectl -n meeting-insights exec deployment/meeting-insights-agent -- \
  sh -c 'curl -sS https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY" \
  | python -c "import sys, json; print(\"\\n\".join(x[\"id\"] for x in json.load(sys.stdin)[\"data\"]))"'
```

`hpa.yaml` 需要 Metrics Server。GKE 預設支援；kind 的最小安裝通常不含 Metrics Server，因此本機成功 demo 不必套用 HPA manifest。

## Amazon Bedrock（本機）

1. `aws configure` 使用 **IAM user** 的 access key，不要用 root。
2. 區域 `us-east-1`，Bedrock console 需已開啟 Claude 模型。
3. `.env`：`CLAUDE_CODE_USE_BEDROCK=1`、`AWS_REGION=us-east-1`、`AGENT_BACKEND=auto`
4. 重啟 uvicorn 後：`aws sts get-caller-identity`（Arn 不應是 `:root`），再用 `aws bedrock list-foundation-models` 確認 Claude 模型。沒有 AWS 憑證時改走 `ANTHROPIC_API_KEY`，兩者都失敗則降級 pipeline。

Fargate 部署與成本見 [infra/README.md](infra/README.md)。CloudFormation 會建立 ECS cluster、task definition、service、CloudWatch log group、task/execution IAM roles 與 security group；它不會建立 Qdrant、ALB/NLB、公開 DNS 或網際網路 ingress。部署需明確提供 `GroqSecretArn` 與 VPC 可達的 `QdrantHost`。

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
- Groq 模型權限不是由程式保證。程式預設 vision model 是 `qwen/qwen3.6-27b`，而 repo 的 Kubernetes／`.env.example` 建議使用 `qwen/qwen3.8-27b`；若 API 回 `model_not_found`，以該 key 的 `/models` 結果覆寫 `GROQ_VISION_MODEL`。
- Claude Agent SDK 需要 `ANTHROPIC_API_KEY`，或 `CLAUDE_CODE_USE_BEDROCK=1` 加上可用的 AWS credentials。
- Fallback 只涵蓋 `is_sdk_startup_error`（啟動、認證、連線、額度），不是所有執行期錯誤都能自動恢復。
- `infra/` 有 ECS Fargate、CloudFormation 與 IAM 模板，**尚未把服務部署到 ECS 叢集**。本機驗證的是 Bedrock 呼叫與最小權限設計。
- kind 已驗證的是 pipeline deployment，不是 Claude Agent SDK deployment；不要將 `backend: "pipeline"` demo 描述成 Claude SDK 的自主 Tool Use 成功執行。
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
  k8s/                 Kubernetes manifests、kind override、部署文件與 demo evidence
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

1. `GET /health` → 說明目前是 `claude` 還是 `pipeline`，不要混淆兩條路徑。
2. `/docs` 上傳 `test-meeting.mp3` + `test-meeting-ppt.png` → 結構化報告（對照 +25.4% / -11.2%）。
3. MCP：`payroll` deny，再對照 `employees` allow。
4. `pytest` 與 `python -m evals.runner` 全過。
5. `kubectl -n meeting-insights get pods,svc` → kind demo 的 replicas、Qdrant 和 ClusterIP；再說明此 demo 是 pipeline mode。
6. 打開 `infra/cloudformation.yaml` 講 Fargate CPU/Memory、Groq secret injection、QdrantHost 與 IAM；用 `estimate_aws_cost` 講成本。
```bash
# 成本 Demo 指令：
python mcp_client.py call estimate_aws_cost \
  --args '{"vcpu":1,"memory_gb":2}'
# 輸出中的:
"total_usd": 48.04
```


**開場：** 主迴圈是 Claude Agent SDK 的規劃與 Tool Use，不是寫死 DAG；Claude 路徑上 MCP 是內部系統唯一出口；安全是沙箱 + allowlist + IAM 疊加；Evals 不靠 live LLM 擋迴歸。內部目錄預設 fixture、Fargate 尚未部署到叢集——請照實講。
