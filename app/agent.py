import os
import base64
from typing import List
from typing_extensions import TypedDict
import httpx

from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from openai import OpenAI


class AgentState(TypedDict):
    audio_bytes: bytes
    image_bytes_list: List[bytes]
    transcript: str
    image_descriptions: List[str]
    final_report: str


_groq_client = None
_vision_llm = None
_synthesis_llm = None


def _get_groq_client() -> OpenAI:
    """Uses Groq's OpenAI-compatible endpoint for Whisper audio transcription."""
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set!")
            
        _groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            http_client=httpx.Client(trust_env=False),
        )
    return _groq_client


def _get_vision_llm() -> ChatGroq:
    """Uses Groq's vision-capable model. max_tokens must stay under Groq OTPM."""
    global _vision_llm
    if _vision_llm is None:
        api_key = os.getenv("GROQ_API_KEY")
        max_tokens = int(os.getenv("GROQ_VISION_MAX_TOKENS", "512"))
        _vision_llm = ChatGroq(
            model=os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b"),
            temperature=0.2,
            max_tokens=max_tokens,
            api_key=api_key,
            http_client=httpx.Client(trust_env=False),
        )
    return _vision_llm


def _get_synthesis_llm() -> ChatGroq:
    """Report synthesis. Cap output so on-demand OTPM (often 1000) is not exceeded."""
    global _synthesis_llm
    if _synthesis_llm is None:
        api_key = os.getenv("GROQ_API_KEY")
        max_tokens = int(os.getenv("GROQ_SYNTHESIS_MAX_TOKENS", "800"))
        _synthesis_llm = ChatGroq(
            model=os.getenv("GROQ_SYNTHESIS_MODEL", "openai/gpt-oss-120b"),
            temperature=0.2,
            max_tokens=max_tokens,
            api_key=api_key,
            http_client=httpx.Client(trust_env=False),
        )
    return _synthesis_llm


def speech_to_text_node(state: AgentState):
    audio_file = ("meeting.mp3", state["audio_bytes"], "audio/mp3")
    transcript_res = _get_groq_client().audio.transcriptions.create(
        model="whisper-large-v3",
        file=audio_file,
    )
    return {"transcript": transcript_res.text}


def vision_analysis_node(state: AgentState):
    descriptions = []
    vision_llm = _get_vision_llm()
    
    for img_bytes in state["image_bytes_list"]:
        base64_image = base64.b64encode(img_bytes).decode("utf-8")
        response = vision_llm.invoke(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "請用條列提取此簡報/圖表的核心數據、趨勢與關鍵文字，控制在 200 字內。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            },
                        },
                    ],
                }
            ]
        )
        descriptions.append(response.content)
    return {"image_descriptions": descriptions}


def synthesize_insights_node(state: AgentState):
    image_insights = (
        " | ".join(state["image_descriptions"])
        if state["image_descriptions"]
        else "（未提供簡報圖片）"
    )
    prompt = f"""
你是一個高階 AI 商業分析師。請結合以下的【會議逐字稿】與【簡報圖片分析】，生成一份結構化的高階會議摘要報告。

【會議逐字稿】：
{state['transcript']}

【簡報圖片分析】：
{image_insights}

請輸出包含以下章節的 Markdown 報告：
1. 📌 會議核心主題與目標
2. 📊 簡報數據與逐字稿交叉對照重點
3. 💡 關鍵決策與 Action Items (需指派執行人與預計時程)
"""
    synthesis_llm = _get_synthesis_llm()
    report = synthesis_llm.invoke(prompt).content
    return {"final_report": report}


workflow = StateGraph(AgentState)
workflow.add_node("speech_processor", speech_to_text_node)
workflow.add_node("vision_processor", vision_analysis_node)
workflow.add_node("synthesizer", synthesize_insights_node)

workflow.set_entry_point("speech_processor")
workflow.add_edge("speech_processor", "vision_processor")
workflow.add_edge("vision_processor", "synthesizer")
workflow.add_edge("synthesizer", END)

multimodal_agent = workflow.compile()