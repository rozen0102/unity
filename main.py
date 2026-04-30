from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import os
import json
from fastapi.responses import FileResponse # 新增這一行載入 FileResponse

app = FastAPI()

# 設定 CORS，允許前端網頁呼叫這支 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 新增這個路由：當 Vercel 誤把首頁請求丟給後端時，強制回傳外層的 index.html
@app.get("/")
async def serve_index():
    return FileResponse("index.html")

# 只需要 Dify 的 API Key，不再需要 LINE 的金鑰
DIFY_API_KEY = os.getenv('DIFY_API_KEY')

# 定義前端傳來的資料格式
class ChatRequest(BaseModel):
    message: str
    user_id: str = "web_user"
    role_name: str = "郭小美"  # 【新增】接收 Unity 傳來的角色名稱，預設為郭小美

# 將路由從 /webhook 改為 /api/chat
@app.post("/api/chat")
async def chat_with_dify(request: ChatRequest):
    if not DIFY_API_KEY:
        raise HTTPException(status_code=500, detail="Vercel 尚未設定 DIFY_API_KEY 環境變數")

    user_message = request.message
    user_id = request.user_id
    role_name = request.role_name  # 【新增】取出角色名稱

    try:
        # 呼叫 Dify 大腦 (Streaming 模式)
        dify_res = requests.post(
            "https://api.dify.ai/v1/chat-messages",
            headers={"Authorization": f"Bearer {DIFY_API_KEY}"},
            json={
                "inputs": {
                    "character_name": role_name  # 【修改】將角色名稱傳遞給 Dify 作為變數
                },
                "query": user_message,
                "response_mode": "streaming", # Agent 必須使用串流模式
                "user": user_id
            },
            stream=True 
        )
        
        # 處理 Dify 錯誤
        if dify_res.status_code != 200:
            error_data = dify_res.json()
            error_msg = error_data.get('message', str(error_data))
            return {"reply": f"⚠️ Dify 大腦回報錯誤：\n{error_msg}"}

        # 成功連線！開始拼湊串流回傳的字串
        answer = ""
        for line in dify_res.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data:'):
                    data_str = decoded_line[5:].strip()
                    try:
                        json_data = json.loads(data_str)
                        # 兼容 Agent 模式 (agent_message) 與 Chatflow 模式 (message)
                        event_type = json_data.get('event')
                        if event_type in ['message', 'agent_message']:
                            # 抓取答案片段並累加
                            answer += json_data.get('answer', '')
                    except json.JSONDecodeError:
                        pass
                        
        if not answer:
            answer = "Dify 處理完畢，但未產生文字回應 (可能只回傳了思考過程，請檢查 Agent 提示詞設定)。"
            
        # 直接把純文字 (Markdown格式) 丟回給前端網頁
        return {"reply": answer}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"伺服器連線例外錯誤：{str(e)}")
