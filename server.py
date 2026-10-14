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



# ---------- Q15: LEDGER AGENT ----------

import json
import re
import urllib.request
import calendar
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import HTTPException

LEDGER_URL = (
    "https://exam.sanand.workers.dev/questionData"
    "?email=24f2000638%40ds.study.iitm.ac.in"
    "&quizSign=ozEhPYU0y%2FiGNIUWoLFL7fiLckiMNlZKjAknkEqP8YVd4rXtq7vV%2BL1PEpyZ84RTz%2FAoZ4Gvbf6ErhhXuBU38UD7uyG2MwlAngBHRhflkqsMPbXk0KmWy4LtXJTrbZ4H0JN5dfte8WBHUKjMZFTZXsAamP5M0I9%2FLxTRdmddQvLZh01rPKobwCuqC2rWLvk2S9JPdNclUOUs1E%2F%2FX0DHvkpEPRZnhFvZVOkiHEkOY250QecJkjkCQSpzf9wqTVQzKfmX%2FNDxdc2VxHxsNKEa9FRr5QueUp50T8vGa%2BTFFbtgS%2BGzKuesHip7IgRD5boVpLBzUfjgzojQC1gRdHGN6Q%3D%3D"
    "&questionId=q-ledger-agent-server&path=%2Fexport"
)

USD_RATE = {"USD": 1.0, "EUR": 1.08, "INR": 0.01114}
LEDGER_CACHE = None


def load_ledger():
    global LEDGER_CACHE

    if LEDGER_CACHE is not None:
        return LEDGER_CACHE

    try:
        request = urllib.request.Request(
            LEDGER_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8-sig")

        # The export normally contains one JSON order per line.
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                rows = parsed
            elif isinstance(parsed, dict) and "orders" in parsed:
                rows = parsed["orders"]
            else:
                rows = [parsed]
        except json.JSONDecodeError:
            rows = [
                json.loads(line)
                for line in raw.splitlines()
                if line.strip()
            ]

        # Keep only the latest version of each order.
        latest = {}
        for row in rows:
            order_id = row.get("id")
            if not order_id:
                continue
            previous = latest.get(order_id)
            if (
                previous is None
                or row.get("updated_at", "") >
                   previous.get("updated_at", "")
            ):
                latest[order_id] = row

        LEDGER_CACHE = list(latest.values())
        return LEDGER_CACHE

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not load ledger data: " + str(exc)
        )


def business_date(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("Asia/Kolkata"))


def usd_amount(row):
    currency = row.get("currency", "USD")
    return float(row.get("amount", 0)) * USD_RATE.get(currency, 1.0)


def solve_ledger_question(question):
    rows = load_ledger()
    q = question.lower()

    # Identify the requested month and year.
    months = {
        name.lower(): number
        for number, name in enumerate(calendar.month_name)
        if name
    }
    months.update({
        name.lower(): number
        for number, name in enumerate(calendar.month_abbr)
        if name
    })

    selected_month = None
    for name, number in months.items():
        if re.search(r"\b" + re.escape(name) + r"\b", q):
            selected_month = number
            break

    year_match = re.search(r"\b(20\d{2})\b", q)
    selected_year = int(year_match.group(1)) if year_match else None

    # Filter by region, product, and customer if mentioned.
    regions = sorted(
        {str(r.get("region", "")) for r in rows if r.get("region")},
        key=len, reverse=True
    )
    selected_region = next(
        (r for r in regions if r.lower() in q), None
    )

    products = sorted(
        {str(r.get("product", "")) for r in rows if r.get("product")},
        key=len, reverse=True
    )
    selected_product = next(
        (p for p in products if p.lower() in q), None
    )

    customer_match = re.search(r"\bc\d+\b", q, re.I)
    selected_customer = (
        customer_match.group(0).upper() if customer_match else None
    )

    filtered = []
    for row in rows:
        if selected_region and row.get("region", "").lower() != selected_region.lower():
            continue
        if selected_product and row.get("product", "").lower() != selected_product.lower():
            continue
        if selected_customer and row.get("customer", "").upper() != selected_customer:
            continue

        try:
            dt = business_date(row["created_at"])
        except Exception:
            continue

        if selected_month and dt.month != selected_month:
            continue
        if selected_year and dt.year != selected_year:
            continue

        filtered.append(row)

    if not filtered:
        return "No matching orders found."

    # Refund questions use refunded orders; revenue uses paid orders.
    is_refund = "refund" in q
    status = "refunded" if is_refund else "paid"
    relevant = [r for r in filtered if r.get("status", "").lower() == status]

    # Count questions.
    if any(word in q for word in ("how many", "number of", "count of", "count the", "count ")):
        if "customer" in q:
            value = len({r.get("customer") for r in relevant if r.get("customer")})
            return str(value)
        if "product" in q and ("different" in q or "unique" in q):
            return str(len({r.get("product") for r in filtered if r.get("product")}))
        return str(len(relevant))

   
    # Highest / top product or customer questions.
    if any(word in q for word in (
        "highest", "top", "most", "best-selling", "best selling"
    )):
        if "customer" in q:
            totals = defaultdict(float)
            for r in relevant:
                customer = r.get("customer", "")
                if customer:
                    totals[customer] += usd_amount(r)
            if totals:
                name = max(totals, key=totals.get)
                return f"{name}: ${totals[name]:.2f} USD"
            return "No matching customer revenue found."

        if "product" in q:
            totals = defaultdict(float)
            for r in relevant:
                product = r.get("product", "")
                if product:
                    totals[product] += usd_amount(r)
            if totals:
                name = max(totals, key=totals.get)
                return name
            return "No matching product revenue found."

   
   

    # Total revenue, refunds, and amount questions.
    is_amount_question = any(
        word in q for word in (
            "revenue", "refund", "earned", "earn", "sales",
            "how much", "total", "in us dollars", "in usd",
            "us dollars", "usd"
        )
    )

   
    if "average" in q or "avg" in q:
        paid_orders = [r for r in relevant if r.get("status", "").lower() == "paid"]
        return f"${sum(usd_amount(r) for r in paid_orders) / len(paid_orders):.2f} USD" if paid_orders else "$0.00 USD"
       
    if is_amount_question:
        total = sum(usd_amount(r) for r in relevant)
        return f"${total:.2f} USD"

    return "I could not determine the requested calculation."

@app.post("/answer")
async def ledger_answer(request: Request):
    body = await request.json()
    question = body.get("question", "")

    if not isinstance(question, str) or not question.strip():
        raise HTTPException(
            status_code=400,
            detail="Please provide a question."
        )

    answer = solve_ledger_question(question)
    return {"answer": answer}
