from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import List
from pydantic import BaseModel
from app.agent import multimodal_agent
from fastapi.middleware.cors import CORSMiddleware

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave"}
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}

app = FastAPI(
    title="Multimodal Meeting Insights API",
    description="結合 Whisper, GPT-4o Vision 與 LangGraph 的多模態會議分析服務",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 允許任何前端/網域存取
    allow_credentials=True,
    allow_methods=["*"],          # 允許 GET, POST 等所有 HTTP 方法
    allow_headers=["*"],          # 允許所有 Header
)
class MeetingAnalysisData(BaseModel):
    transcript: str
    image_insights: List[str]
    report: str

class MeetingAnalysisResponse(BaseModel):
    status: str
    data: MeetingAnalysisData


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Multimodal Agent API"}


@app.post(
    "/api/v1/analyze-meeting", 
    response_model=MeetingAnalysisResponse,
    summary="多模態會議分析",
    description="結合語音與圖片自動產出結構化 Markdown 報告"
)
async def analyze_meeting(
    audio: UploadFile = File(..., description="會議語音檔 (.mp3, .wav)"),
    images: List[UploadFile] = File([], description="簡報或白板截圖"),
):
    if audio.content_type and audio.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的音訊格式: {audio.content_type}。請上傳 .mp3 或 .wav 檔案。",
        )

    for image in images:
        if image.content_type and image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支援的圖片格式: {image.content_type}。請上傳 .png 或 .jpg 檔案。",
            )

    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="音訊檔案為空。")

        image_bytes_list = []
        for img in images:
            img_bytes = await img.read()
            if img_bytes:
                image_bytes_list.append(img_bytes)

        initial_state = {
            "audio_bytes": audio_bytes,
            "image_bytes_list": image_bytes_list,
            "transcript": "",
            "image_descriptions": [],
            "final_report": "",
        }

        final_state = await multimodal_agent.ainvoke(initial_state)

        return {
            "status": "success",
            "data": {
                "transcript": final_state["transcript"],
                "image_insights": final_state["image_descriptions"],
                "report": final_state["final_report"],
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"多模態處理失敗: {str(e)}")
