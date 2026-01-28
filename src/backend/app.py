import uvicorn
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.staticfiles import StaticFiles
from starlette.responses import RedirectResponse
from configuration import config
from chat_service import ChatService
from backend.schemas import Question, Answer
from starlette.middleware.sessions import SessionMiddleware
import logging
logging.basicConfig(format="%(asctime)s %(filename)s %(message)s", level=logging.INFO)
app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key="test_key",  # 用于签名 Cookie
    max_age=3600,  # session 过期时间（秒）
    https_only=False,  # 开发时设为 False，生产建议 True
    same_site="lax"    # 安全策略
)

app.mount("/static", StaticFiles(directory=str(config.WEB_STATIC_DIR)), name="static")

service = ChatService()

@app.get("/")
def read_root():
    return RedirectResponse("/static/index.html")

@app.post("/chat")
def read_item(question: Question, request: Request):
    # 维护Session，使用Session来唯一标记维护，通过langchain agent来保存对话历史记录
    session = request.session
    # 用户首次输入时，没有session_id，需要生成session_id
    if "session_id" not in session:
        import uuid
        session["session_id"] = str(uuid.uuid4())

    current_session_id = session["session_id"]
    # print(f"session_id: {current_session_id}")

    return StreamingResponse(service.chat(question.message, session_id=current_session_id), media_type="text/plain")

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
