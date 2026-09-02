import base64
from typing import TypedDict, List

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from openai import OpenAI


class AgentState(TypedDict):
    audio_bytes: bytes
    image_bytes_list: List[bytes]
    transcript: str
    image_descriptions: List[str]
    final_report: str


_client = None
_llm = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    return _llm


def speech_to_text_node(state: AgentState):
    audio_file = ("meeting.mp3", state["audio_bytes"], "audio/mp3")
    transcript_res = _get_client().audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
    )
    return {"transcript": transcript_res.text}


def vision_analysis_node(state: AgentState):
    descriptions = []
    for img_bytes in state["image_bytes_list"]:
        base64_image = base64.b64encode(img_bytes).decode("utf-8")
        response = _get_llm().invoke(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "請詳細提取此會議簡報/白板截圖中的核心數據、圖表趨勢與關鍵文字：",
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
    report = _get_llm().invoke(prompt).content
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
