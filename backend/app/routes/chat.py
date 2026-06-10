from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("")
async def chat(request: Request):
    # TODO Faz 5/6: Anthropic chat + getProjectContext / bot-manager status unported.
    return JSONResponse(status_code=501, content={"error": "not implemented yet (Faz 5-6)"})
