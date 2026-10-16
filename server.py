import hashlib
import json
import re
import urllib.request
import calendar
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="IITM MCP Server")
EMAIL = "24f2000638@ds.study.iitm.ac.in"
BUSINESS_TZ = ZoneInfo("Asia/Kolkata")

# Keep the quiz-provided signed URL exactly as supplied by the assignment.
DATA_BASE = (
    "https://exam.sanand.workers.dev/questionData"
    "?email=24f2000638%40ds.study.iitm.ac.in"
    "&quizSign=ozEhPYU0y%2FiGNIUWoLFL7fiLckiMNlZKjAknkEqP8YVd4rXtq7vV%2BL1PEpyZ84RTz%2FAoZ4Gvbf6ErhhXuBU38UD7uyG2MwlAngBHRhflkqsMPbXk0KmWy4LtXJTrbZ4H0JN5dfte8WBHUKjMZFTZXsAamP5M0I9%2FLxTRdmddQvLZh01rPKobwCuqC2rWLvk2S9JPdNclUOUs1E%2F%2FX0DHvkpEPRZnhFvZVOkiHEkOY250QecJkjkCQSpzf9wqTVQzKfmX%2FNDxdc2VxHxsNKEa9FRr5QueUp50T8vGa%2BTFFbtgS%2BGzKuesHip7IgRD5boVpLBzUfjgzojQC1gRdHGN6Q%3D%3D"
    "&questionId=q-ledger-agent-server&path=%2Fexport"
)
RATES_URL = DATA_BASE.replace("path=%2Fexport", "path=%2Frates")

TOOL = {
    "name": "solve_challenge",
    "description": "Solve the current exam challenge using the HTTP request header.",
    "inputSchema": {"type": "object", "properties": {}},
}


def fetch_json_or_lines(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read().decode("utf-8-sig")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        items = []
        for line in raw.splitlines():
            if line.strip():
                items.append(json.loads(line))
        return items


def extract_orders(payload):
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("orders"), list):
            rows = payload["orders"]
        elif isinstance(payload.get("data"), list):
            rows = payload["data"]
        else:
            raise ValueError("Export JSON did not contain an orders list")
    else:
        raise ValueError("Unexpected export format")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Export contains a non-object order row")
    return rows


def timestamp_key(value):
    if not value:
        return float("-inf")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BUSINESS_TZ)
    return dt.astimezone(timezone.utc).timestamp()


def deduplicate_orders(rows):
    latest = {}
    for row in rows:
        order_id = row.get("id")
        if order_id is None:
            continue
        old = latest.get(order_id)
        if old is None or timestamp_key(row.get("updated_at")) > timestamp_key(old.get("updated_at")):
            latest[order_id] = row
    return list(latest.values())


def extract_rates(payload):
    # Expected source shape: {"description": ..., "usd_per_unit": {"USD": 1, ...}}
    if isinstance(payload, dict):
        rates = payload.get("usd_per_unit")
        if isinstance(rates, dict) and rates:
            return {str(k).upper(): float(v) for k, v in rates.items()}
    raise ValueError("Rates response did not contain usd_per_unit")


@lru_cache(maxsize=1)
def load_data():
    try:
        raw_orders = extract_orders(fetch_json_or_lines(DATA_BASE))
        rates = extract_rates(fetch_json_or_lines(RATES_URL))
        orders = deduplicate_orders(raw_orders)
        if not orders:
            raise ValueError("No orders found in export")
        return orders, rates
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load ledger/rates data: {exc}")


def parse_business_date(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BUSINESS_TZ)
    return dt.astimezone(BUSINESS_TZ)



def amount_usd(row, rates):
    currency = str(row.get("currency", "USD")).upper()
    if currency not in rates:
        raise ValueError(
            f"Missing USD conversion rate for currency {currency}"
        )
    amount = float(row.get("amount", 0) or 0)
    return round(amount * rates[currency] + 1e-10, 2)



def find_month_year(question):
    q = question.lower()
    month_map = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}
    month_map.update({name.lower(): n for n, name in enumerate(calendar.month_abbr) if name})
    month = None
    for name in sorted(month_map, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", q):
            month = month_map[name]
            break
    match = re.search(r"\b(20\d{2})\b", q)
    return month, int(match.group(1)) if match else None


def select_dimension(question, rows, field):
    q = question.casefold()
    values = {str(row.get(field, "")).strip() for row in rows if row.get(field) not in (None, "")}
    for value in sorted(values, key=len, reverse=True):
        if value.casefold() in q:
            return value
    return None


def answer_question(question):
    orders, rates = load_data()
    q = question.strip().lower()
    month, year = find_month_year(q)
    region = select_dimension(q, orders, "region")
    product = select_dimension(q, orders, "product")
    customer_match = re.search(r"\bc\d+\b", q, re.I)
    customer = customer_match.group(0).upper() if customer_match else None

    filtered = []
    for row in orders:
        if region and str(row.get("region", "")).casefold() != region.casefold():
            continue
        if product and str(row.get("product", "")).casefold() != product.casefold():
            continue
        if customer and str(row.get("customer", "")).upper() != customer:
            continue
        try:
            dt = parse_business_date(row["created_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if month is not None and dt.month != month:
            continue
        if year is not None and dt.year != year:
            continue
        filtered.append(row)

    is_refund = "refund" in q
    if is_refund:
        relevant = [r for r in filtered if str(r.get("status", "")).lower() == "refunded"]
    else:
        # The assignment explicitly says only paid orders count as revenue.
        relevant = [r for r in filtered if str(r.get("status", "")).lower() == "paid"]

    # Counts
    if any(term in q for term in ("how many", "number of", "count of", "count the", "count ")):
        if "customer" in q:
            return str(len({r.get("customer") for r in relevant if r.get("customer")}))
        if "product" in q and any(term in q for term in ("different", "unique")):
            return str(len({r.get("product") for r in filtered if r.get("product")}))
        return str(len(relevant))

    # Ranking questions
    ranking = any(term in q for term in ("highest", "top", "most", "best-selling", "best selling"))
    if ranking and ("customer" in q or "product" in q):
        field = "customer" if "customer" in q else "product"
        totals = defaultdict(float)
        for row in relevant:
            label = row.get(field)
            if label:
                totals[str(label)] += amount_usd(row, rates)
        if not totals:
            return "No matching results found."
        best = sorted(totals.items(), key=lambda item: (-item[1], item[0].casefold()))[0]
        return f"{best[0]}: ${best[1]:.2f} USD" if field == "customer" else best[0]

    # Amount/average questions
    is_amount = any(term in q for term in ("revenue", "refund", "earned", "earn", "sales", "how much", "total", "in us dollars", "in usd", "us dollars", "usd", "average", "avg"))
    if is_amount:
        values = [amount_usd(row, rates) for row in relevant]
        if "average" in q or re.search(r"\bavg\b", q):
            return f"${(sum(values) / len(values)) if values else 0:.2f} USD"
        return f"${sum(values):.2f} USD"

    return "I could not determine the requested calculation."


# Q14 MCP challenge endpoint â€” intentionally preserved.
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    body = await request.json()
    method = body.get("method")
    request_id = body.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": body.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}}, "serverInfo": {"name": "iitm-exam-mcp", "version": "2.0.0"}}})
    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {}})
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}})
    if method == "tools/call":
        params = body.get("params", {})
        if params.get("name") != "solve_challenge":
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Unknown tool"}})
        challenge = request.headers.get("x-exam-challenge", "")
        if len(challenge) != 32 or any(c not in "0123456789abcdef" for c in challenge):
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": "Missing or invalid challenge header"}], "isError": True}})
        digest = hashlib.sha256(f"{challenge}:{EMAIL}".encode("utf-8")).hexdigest()[:16]
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": digest}]}})
    if request_id is None:
        return Response(status_code=202)
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})


@app.post("/answer")
async def ledger_answer(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    question = body.get("question", "") if isinstance(body, dict) else ""
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(status_code=400, detail="Please provide a question.")
    return {"answer": answer_question(question)}


@app.get("/health")
async def health():
    return {"status": "ok"}
