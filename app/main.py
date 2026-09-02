import uuid
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from app.agent import multimodal_agent
from app.vector_store import index_report, search_reports

load_dotenv()

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave"}
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}

app = FastAPI(
    title="Multimodal Meeting Insights API",
    description="結合 Whisper, Qwen Vision, LangGraph 與 Qdrant RAG 的多模態會議分析微服務",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Pydantic Schemas
# ------------------------------------------------------------------
class MeetingAnalysisData(BaseModel):
    transcript: str
    image_insights: List[str]
    report: str

class MeetingAnalysisResponse(BaseModel):
    status: str
    data: MeetingAnalysisData

class SearchResultItem(BaseModel):
    content: str
    metadata: dict

class SearchResponse(BaseModel):
    status: str
    results: List[SearchResultItem]


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
@app.get("/health", summary="健康檢查")
async def health_check():
    return {"status": "healthy", "service": "Multimodal Agent API"}


@app.post(
    "/api/v1/analyze-meeting", 
    response_model=MeetingAnalysisResponse,
    summary="多模態會議分析與 RAG 索引",
    description="結合語音與圖片產出 Markdown 報告，並自動存入 Qdrant 向量庫"
)
async def analyze_meeting(
    audio: UploadFile = File(..., description="會議語音檔 (.mp3, .wav)"),
    # 💡 將圖片拆分為獨立的 UploadFile 欄位，解決 Swagger UI 無法顯示多檔選擇器的問題
    image1: Optional[UploadFile] = File(None, description="簡報或白板截圖 1 (.png, .jpg)"),
    image2: Optional[UploadFile] = File(None, description="簡報或白板截圖 2 (.png, .jpg)"),
    image3: Optional[UploadFile] = File(None, description="簡報或白板截圖 3 (.png, .jpg)"),
):
    # 1. 驗證語音格式
    if audio.content_type and audio.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的音訊格式: {audio.content_type}。請上傳 .mp3 或 .wav 檔案。",
        )

    # 2. 彙整上傳的圖片並驗證格式
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
            image_bytes_list.append(img_bytes)

    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="音訊檔案為空。")

        initial_state = {
            "audio_bytes": audio_bytes,
            "image_bytes_list": image_bytes_list,
            "transcript": "",
            "image_descriptions": [],
            "final_report": "",
        }

        final_state = await multimodal_agent.ainvoke(initial_state)

        report = final_state.get("final_report", "")
        
        # 自動建立 Vector Index 至 Qdrant
        if report:
            meeting_id = str(uuid.uuid4())[:8]
            index_report(
                report_text=report,
                metadata={
                    "meeting_id": meeting_id,
                    "filename": audio.filename,
                    "transcript_snippet": final_state.get("transcript", "")[:100],
                }
            )

        return {
            "status": "success",
            "data": {
                "transcript": final_state.get("transcript", ""),
                "image_insights": final_state.get("image_descriptions", []),
                "report": report,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"多模態處理失敗: {str(e)}")


@app.get(
    "/api/v1/search",
    response_model=SearchResponse,
    summary="搜尋歷史會議記錄 (RAG)",
    description="利用向量相似度從 Qdrant 檢索相關的歷史會議摘要與決策"
)
async def search_meetings(
    query: str = Query(..., description="搜尋關鍵字或問題，例如：'Q2 門市營收'"),
    limit: int = Query(3, ge=1, le=10, description="回傳結果筆數限制")
):
    try:
        results = search_reports(query=query, limit=limit)
        return {
            "status": "success",
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"向量檢索失敗: {str(e)}")