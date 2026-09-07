import os
import uuid
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from app.agent import multimodal_agent
from app.claude_agent import claude_sdk_importable, run_claude_agent
from app.config import AGENT_BACKEND, has_anthropic_credentials
from app.sandbox import SandboxError, create_job_dir, relative_to_sandbox, write_bytes
from app.vector_store import index_report, search_reports

load_dotenv()

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave"}
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}

app = FastAPI(
    title="Multimodal Meeting Insights API",
    description="Claude Agent SDK + MCP + LangGraph specialists + Qdrant RAG",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MeetingAnalysisData(BaseModel):
    transcript: str
    image_insights: List[str]
    report: str
    tools_used: List[str] = []
    backend: str = "pipeline"


class MeetingAnalysisResponse(BaseModel):
    status: str
    data: MeetingAnalysisData


class SearchResultItem(BaseModel):
    content: str
    metadata: dict


class SearchResponse(BaseModel):
    status: str
    results: List[SearchResultItem]


def resolve_backend() -> str:
    if AGENT_BACKEND in {"pipeline", "claude"}:
        return AGENT_BACKEND
    if has_anthropic_credentials() and claude_sdk_importable():
        return "claude"
    return "pipeline"


@app.get("/health", summary="健康檢查")
async def health_check():
    backend = resolve_backend()
    return {
        "status": "healthy",
        "service": "Multimodal Agent API",
        "backend": backend,
        "claude_sdk": claude_sdk_importable(),
        "anthropic_or_bedrock": has_anthropic_credentials(),
    }


@app.post(
    "/api/v1/analyze-meeting",
    response_model=MeetingAnalysisResponse,
    summary="多模態會議分析與 RAG 索引",
    description="Claude Agent SDK（若已設定金鑰）自主規劃並呼叫 MCP tools；否則走 LangGraph pipeline。",
)
async def analyze_meeting(
    audio: UploadFile = File(..., description="會議語音檔 (.mp3, .wav)"),
    image1: Optional[UploadFile] = File(None, description="簡報或白板截圖 1 (.png, .jpg)"),
    image2: Optional[UploadFile] = File(None, description="簡報或白板截圖 2 (.png, .jpg)"),
    image3: Optional[UploadFile] = File(None, description="簡報或白板截圖 3 (.png, .jpg)"),
    user_query: Optional[str] = Query(None, description="額外指示，例如：對照上次 Q2 決議"),
):
    if audio.content_type and audio.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的音訊格式: {audio.content_type}。請上傳 .mp3 或 .wav 檔案。",
        )

    uploaded_images = [img for img in [image1, image2, image3] if img is not None and img.filename]
    image_bytes_list = []
    for image in uploaded_images:
        if image.content_type and image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支援的圖片格式 ({image.filename}): {image.content_type}。請上傳 .png 或 .jpg 檔案。",
            )
        img_bytes = await image.read()
        if img_bytes:
            image_bytes_list.append((image.filename, img_bytes))

    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="音訊檔案為空。")

        backend = resolve_backend()
        tools_used: List[str] = []

        if backend == "claude":
            job_dir = create_job_dir()
            audio_path = write_bytes(job_dir, audio.filename or "meeting.mp3", audio_bytes)
            image_paths = [
                write_bytes(job_dir, name or f"slide-{idx}.png", data)
                for idx, (name, data) in enumerate(image_bytes_list, start=1)
            ]
            result = await run_claude_agent(
                audio_path=relative_to_sandbox(audio_path),
                image_paths=[relative_to_sandbox(path) for path in image_paths],
                user_query=user_query,
            )
            transcript = result.get("transcript") or ""
            image_insights = result.get("image_insights") or []
            report = result.get("report") or ""
            tools_used = result.get("tools_used") or []
        else:
            initial_state = {
                "audio_bytes": audio_bytes,
                "image_bytes_list": [data for _, data in image_bytes_list],
                "transcript": "",
                "image_descriptions": [],
                "final_report": "",
            }
            final_state = await multimodal_agent.ainvoke(initial_state)
            transcript = final_state.get("transcript", "")
            image_insights = final_state.get("image_descriptions", [])
            report = final_state.get("final_report", "")
            tools_used = ["speech_processor", "vision_processor", "synthesizer"]

        if report:
            meeting_id = str(uuid.uuid4())[:8]
            index_report(
                report_text=report,
                metadata={
                    "meeting_id": meeting_id,
                    "filename": audio.filename,
                    "transcript_snippet": transcript[:100],
                    "backend": backend,
                },
            )

        return {
            "status": "success",
            "data": {
                "transcript": transcript,
                "image_insights": image_insights,
                "report": report,
                "tools_used": tools_used,
                "backend": backend,
            },
        }
    except HTTPException:
        raise
    except SandboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"多模態處理失敗: {str(e)}")


@app.get(
    "/api/v1/search",
    response_model=SearchResponse,
    summary="搜尋歷史會議記錄 (RAG)",
    description="利用向量相似度從 Qdrant 檢索相關的歷史會議摘要與決策",
)
async def search_meetings(
    query: str = Query(..., description="搜尋關鍵字或問題，例如：'Q2 門市營收'"),
    limit: int = Query(3, ge=1, le=10, description="回傳結果筆數限制"),
):
    try:
        results = search_reports(query=query, limit=limit)
        return {"status": "success", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"向量檢索失敗: {str(e)}")
