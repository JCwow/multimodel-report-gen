# AWS Fargate + Bedrock 部署

Agent 以 **ECS Fargate** 跑 Claude Agent SDK（容器內含 Python + Node.js Claude Code CLI），模型走 **Amazon Bedrock**（`CLAUDE_CODE_USE_BEDROCK=1`），不必把 Anthropic API key 放進 task。

## 架構

```
ALB / 內部 NLB (optional)
        │
        ▼
ECS Fargate task  (1024 CPU / 2048 MB)
  uvicorn :8000
    └── Claude Agent SDK  (MCP client, tools=[], no Bash)
          └── in-process MCP server
                ├── Groq Whisper / Vision specialists
                ├── Qdrant RAG
                ├── Internal directory / calendar API
                └── S3 prefix meetings/*  (IAM 限制)
```

沙箱分三層：

1. 應用層 `app/sandbox.py`：路徑白名單、擋 `.env`、timeout、檔案大小
2. Agent SDK：`tools=[]` 拿掉 Bash/Read/Write；可開 bubblewrap（Fargate 上常不可用，故預設關）
3. IAM：task role 只能 `bedrock:InvokeModel` + `s3:.../meetings/*`，不能讀 Secrets Manager、不能 AssumeRole

## 部署步驟

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
REPO=meeting-insights-agent

aws ecr create-repository --repository-name $REPO --region $REGION || true
aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

docker build -t $REPO .
docker tag $REPO:latest $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest

aws secretsmanager create-secret --name meeting-insights/groq --secret-string "$GROQ_API_KEY"

aws cloudformation deploy \
  --stack-name meeting-insights \
  --template-file infra/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ImageUri=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest \
      VpcId=vpc-xxxxxxxx \
      SubnetIds=subnet-aaaa,subnet-bbbb \
      Cpu=1024 \
      Memory=2048
```

Bedrock 主控台需先 enable Claude 模型（建議 Haiku 做規劃、需要長報告再升 Sonnet）。

本地對照：

```bash
docker compose up --build
```

## 成本（us-east-1 約略，用來面試講規劃）

| 項目 | 假設 | 月費 |
| --- | --- | --- |
| Fargate 1 vCPU / 2 GB × 730h on-demand | 常駐 1 task | ~$36 |
| 同上，Graviton ARM64 | 約 -20% | ~$29 |
| 同上，下班關機 12h/day | 365h | ~$18 |
| Bedrock Sonnet 2M in / 0.4M out | 規劃預設 | ~$12 |
| Bedrock Haiku 同 token | 換小模型 | ~$3.2 |
| Qdrant 1 vCPU / 2 GB | 獨立 service | ~$36 |
| CloudWatch logs 14 天 | 低 | <$2 |

**優化順序（面試可講）：**

1. `AGENT_MAX_TURNS=12` + `AGENT_MAX_BUDGET_USD=0.50` 硬上限
2. 規劃用 Haiku、合成報告才用 Sonnet
3. Fargate 0.5 vCPU / 1 GB 若 QPS 低；或 scheduled scale-to-zero
4. Whisper/Vision 走 Groq，避免 Bedrock 做多模態
5. 圖片 pHash 去重，減少 Vision token
6. Graviton + Fargate Spot（可中斷的批次分析）

用 MCP tool `estimate_aws_cost` 可即時算同一組假設。
