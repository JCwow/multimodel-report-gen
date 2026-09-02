import os
import sys
import asyncio

# 確保專案根目錄在 Python Module 搜尋路徑中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer
from app.agent import multimodal_agent
from app.vector_store import search_reports

# 初始化 MCPServer 服務 (MCP 2.x API)
mcp = MCPServer("Multimodal Meeting Insights")

@mcp.tool()
async def analyze_meeting_files(audio_path: str, image_paths: list[str] = []) -> str:
    """分析會議語音檔與簡報圖片檔，自動生成結構化 Markdown 會議報告"""
    if not os.path.exists(audio_path):
        return f"錯誤：找不到語音檔案 {audio_path}"
        
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
        
    images_bytes = []
    for path in image_paths:
        if os.path.exists(path):
            with open(path, "rb") as f:
                images_bytes.append(f.read())
            
    inputs = {
        "audio_bytes": audio_bytes,
        "image_bytes_list": images_bytes,
        "transcript": "",
        "image_descriptions": [],
        "final_report": "",
    }
    
    result = await multimodal_agent.ainvoke(inputs)
    return result.get("final_report", "無法生成報告")

@mcp.tool()
async def query_historical_meetings(query: str) -> str:
    """從 Qdrant 向量資料庫搜尋歷史會議記錄 (RAG)"""
    results = search_reports(query=query, limit=3)
    if not results:
        return "未找到相關歷史會議記錄。"
    
    formatted = []
    for idx, doc in enumerate(results, 1):
        formatted.append(f"### 歷史記錄 {idx}\n{doc['content']}\n")
    return "\n---\n".join(formatted)

if __name__ == "__main__":
    mcp.run(transport="stdio")