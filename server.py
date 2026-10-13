import hashlib
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()

EMAIL = "24f2000638@ds.study.iitm.ac.in"

TOOL = {
    "name": "solve_challenge",
    "description": "Solve the current exam challenge using the HTTP request header.",
    "inputSchema": {
        "type": "object",
        "properties": {}
    }
}


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    body = await request.json()
    method = body.get("method")
    request_id = body.get("id")

    if method == "notifications/initialized":
        return Response(status_code=202)

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": body.get("params", {}).get(
                    "protocolVersion", "2025-03-26"
                ),
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "iitm-exam-mcp",
                    "version": "1.0.0"
                }
            }
        })

    if method == "ping":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {}
        })

    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": [TOOL]}
        })

    if method == "tools/call":
        params = body.get("params", {})

        if params.get("name") != "solve_challenge":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "Unknown tool"
                }
            })

        challenge = request.headers.get("x-exam-challenge", "")

        if len(challenge) != 32 or any(
            c not in "0123456789abcdef" for c in challenge
        ):
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{
                        "type": "text",
                        "text": "Missing or invalid challenge header"
                    }],
                    "isError": True
                }
            })

        message = f"{challenge}:{EMAIL}".encode("utf-8")
        answer = hashlib.sha256(message).hexdigest()[:16]

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": answer}]
            }
        })

    if request_id is None:
        return Response(status_code=202)

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": "Method not found"
        }
    })
