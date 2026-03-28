from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import requests
import os
import json
import re

app = Flask(__name__)

client = OpenAI(
    base_url="https://api.featherless.ai/v1",
    api_key="rc_31cc85fe1260d49fca946c9cec89b488dfd4536e85e2b22f3edd2e8036ff2b0e",
)

BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "YOUR_BRIGHTDATA_API_KEY")
BRIGHTDATA_ZONE = os.getenv("BRIGHTDATA_ZONE", "web_unlocker1")

CATEGORY_ORDER = ["food", "shopping", "transport", "subscriptions", "bills", "healthcare", "grocery", "fitness"]

# Keywords that signal an incoming credit/refund (not an expense)
CREDIT_KEYWORDS = [
    'received', 'refund', 'cashback', 'credited', 'salary',
    'split', 'returned', 'credit', 'income', 'earning',
    'deposited', 'reversal', 'reimbursed',
]

# ── Regex patterns ──────────────────────────────────────────────────────────
AMOUNT_RE  = re.compile(r'(?:₹|Rs\.?\s*|INR\s*)([0-9,]+(?:\.[0-9]{1,2})?)', re.IGNORECASE)
BARE_NUM_RE = re.compile(r'\b([0-9]{2,}(?:,[0-9]+)*(?:\.[0-9]{1,2})?)\s*(?:/-)?(?:\s|$)')
DATE_RE    = re.compile(
    r'\b(\d{1,2}[\s\-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
    r'(?:[\s\-/]\d{2,4})?'
    r'|\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?)\b',
    re.IGNORECASE
)
NOISE_RE   = re.compile(
    r'\b(?:paid|debited|debit|payment\s+to|txn\s+at|transaction|upi|neft|imps|'
    r'vpa|a/c|ac\b|acct|account|ref(?:erence)?(?:\s+no\.?)?)\b',
    re.IGNORECASE
)
# Separate pattern for ref codes: only uppercase+digits, 12+ chars (avoids stripping merchant names)
REFCODE_RE = re.compile(r'\b[A-Z0-9]{12,}\b')


# ── Server-side transaction parser ──────────────────────────────────────────
def parse_raw_text(text: str):
    """
    Parse every line into (expense_list, credit_list).
    Each item: {"merchant": str, "date": str, "amount": float, "category": ""}
    100% server-side — no model involved.
    """
    expenses: list[dict] = []
    credits: list[dict] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # ① Find amount
        amt_m = AMOUNT_RE.search(line)
        if not amt_m:
            amt_m = BARE_NUM_RE.search(line)
        if not amt_m:
            continue

        try:
            amount = float(amt_m.group(1).replace(',', ''))
        except (ValueError, IndexError):
            continue
        if amount <= 0:
            continue

        # ② Find date
        date_m = DATE_RE.search(line)
        date_str = date_m.group(1).strip() if date_m else ''

        # ③ Build merchant name (strip amount, date, noise)
        merchant = line
        merchant = AMOUNT_RE.sub('', merchant)
        merchant = BARE_NUM_RE.sub('', merchant)
        if date_m:
            # Remove the full date match
            merchant = merchant.replace(date_m.group(0), '')
        # Remove stray month abbreviations left behind (Jan, Feb, Aug, etc.)
        merchant = re.sub(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b', '', merchant, flags=re.IGNORECASE)
        merchant = NOISE_RE.sub(' ', merchant)
        merchant = REFCODE_RE.sub('', merchant)
        merchant = re.sub(r'[₹:,|\-]+', ' ', merchant)
        merchant = re.sub(r'\s+', ' ', merchant).strip().strip(':,-.')
        if not merchant:
            merchant = 'Unknown'

        # ④ Detect credit / refund
        line_lower = line.lower()
        # Check for "from <Name>" pattern too
        from_person = bool(re.search(r'\bfrom\s+[A-Z][a-z]', line))
        is_credit = from_person or any(kw in line_lower for kw in CREDIT_KEYWORDS)

        entry: dict = {'merchant': merchant, 'date': date_str, 'amount': amount, 'category': ''}
        (credits if is_credit else expenses).append(entry)

    return expenses, credits


# ── Server-side analytics ───────────────────────────────────────────────────
def compute_analytics(data: dict, expense_txns: list[dict]) -> dict:
    """
    Recalculate every numeric field from the parsed transaction list.
    The model's numbers are NEVER used for math — only for categories/insights.
    """
    # Core stats
    raw_total: float = float(sum(float(t["amount"]) for t in expense_txns))
    total_spent: float = int(raw_total * 100) / 100.0
    tx_count: int = len(expense_txns)
    avg_tx: float = (int((total_spent / tx_count) * 100) / 100.0) if tx_count > 0 else 0.0

    data["total_spent"] = total_spent
    data["transaction_count"] = tx_count
    data["avg_transaction"] = avg_tx

    # Subscriptions
    sub_txns = [t for t in expense_txns if str(t.get("category", "")).lower() == "subscriptions"]
    data["subscriptions_total"] = int(float(sum(float(t["amount"]) for t in sub_txns)) * 100) / 100.0
    data["subscriptions_count"] = len(sub_txns)

    # Category totals
    cat_totals: dict[str, float] = {}
    for t in expense_txns:
        cat = str(t.get("category", "shopping")).lower()
        if cat not in CATEGORY_ORDER:
            cat = "shopping"
        cat_totals[cat] = cat_totals.get(cat, 0.0) + float(t["amount"])

    # Top category
    if cat_totals:
        top_cat = max(cat_totals, key=lambda k: cat_totals[k])
        top_amt = cat_totals[top_cat]
        top_pct = int((top_amt / total_spent) * 100) if total_spent > 0 else 0
        data["top_category_name"] = top_cat.title()
        data["top_category_amount"] = int(float(top_amt) * 100) / 100.0
        data["top_category_percent"] = f"{top_pct}%"
    else:
        data["top_category_name"] = "N/A"
        data["top_category_amount"] = 0.0
        data["top_category_percent"] = "0%"

    # Donut — largest-remainder method (always sums to 100)
    if total_spent > 0:
        raw_pcts = [cat_totals.get(cat, 0.0) / total_spent * 100 for cat in CATEGORY_ORDER]
        floors: list[int] = []
        remainders: list[tuple[float, int]] = []
        for idx, pct in enumerate(raw_pcts):
            f = int(pct)
            floors.append(f)
            remainders.append((pct - float(f), idx))
        remainder_needed: int = 100 - int(sum(floors))
        remainders.sort(reverse=True)
        for i in range(remainder_needed):
            floors[remainders[i][1]] += 1
        data["donut"] = floors
    else:
        data["donut"] = [0] * 8

    # Line chart — one point per transaction, in original input order
    # (users paste data chronologically, so input order = correct order)
    line_labels: list[str] = []
    line_data: list[float] = []
    for t in expense_txns:
        merchant = str(t.get("merchant", "Tx") or "Tx")
        date = str(t.get("date", "") or "")
        if date:
            label = f"{date}: {merchant}"
        else:
            label = merchant
        line_labels.append(label[:25])  # type: ignore[index]
        line_data.append(int(float(t["amount"]) * 100) / 100.0)

    data["line_labels"] = line_labels
    data["line_data"] = line_data
    return data


# ── JSON extractor ──────────────────────────────────────────────────────────
def extract_json(text: str) -> dict:
    text = re.sub(r'```(?:json)?\s*', '', text).strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in AI response")
    json_str = text[start:end + 1]  # type: ignore
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)  # trailing commas
    return json.loads(json_str)


# ── Bright Data scraper ─────────────────────────────────────────────────────
def scrape_with_brightdata(url: str) -> str:
    print(f"Scraping {url} via Bright Data...")
    response = requests.post(
        "https://api.brightdata.com/request",
        headers={"Authorization": f"Bearer {BRIGHTDATA_API_KEY}", "Content-Type": "application/json"},
        json={"zone": BRIGHTDATA_ZONE, "url": url, "format": "raw"},
    )
    if response.status_code != 200:
        raise Exception(f"Bright Data Error {response.status_code}: {response.text}")
    return response.text


# ── Routes ──────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze_expenses():
    body = request.json
    if not body:
        return jsonify({"error": "No JSON body received", "response": "No JSON body received"}), 400
    user_input: str = body.get("prompt", "").strip()
    if not user_input:
        return jsonify({"error": "Empty prompt", "response": "Empty prompt"}), 400

    try:
        # ── Step 1: get raw text ────────────────────────────────────────────
        if user_input.startswith("http://") or user_input.startswith("https://"):
            raw_text = scrape_with_brightdata(user_input)[:6000]
        else:
            raw_text = user_input

        # ── Step 2: server-side parsing — 100% accurate ─────────────────────
        expenses, credits = parse_raw_text(raw_text)
        print(f"Parsed {len(expenses)} expenses, {len(credits)} credits")

        if not expenses:
            return jsonify({
                "error": "No transactions found. Please paste bank SMS, statements, or transaction lines.",
                "response": "No transactions found."
            }), 400

        # ── Step 3: ask model ONLY for categories + insights ─────────────────
        tx_lines = "\n".join(
            f"{i+1}. {t['merchant']}" + (f" ({t['date']})" if t['date'] else "") + f" INR {t['amount']}"
            for i, t in enumerate(expenses)
        )

        system_prompt = """You are a financial categorizer. Output ONLY valid JSON, nothing else.

CATEGORIES (pick exactly one per transaction):
food, grocery, transport, shopping, subscriptions, bills, healthcare, fitness

- bills: rent, internet, electricity, phone bill, gas, maintenance
- food: restaurants, cafes, food delivery (Swiggy, Zomato, Pizza Hut)
- grocery: BigBasket, supermarket, DMart, kirana
- transport: petrol, Uber, Ola, metro, train, flight, fuel
- shopping: clothes, shoes, electronics, e-commerce, Amazon, events, entertainment, movies, everything else
- subscriptions: Netflix, Spotify, Prime, Hotstar, recurring monthly fee
- healthcare: medicine, pharmacy (PharmEasy, 1mg), doctor, hospital
- fitness: gym membership only

Return exactly this JSON (categories array must have same length as transactions list):
{"categories":["cat1","cat2"],"waste_score":0,"patterns":["p1","p2","p3"],"action_plan":[{"title":"","desc":"","saving":""}]}"""

        user_prompt = f"Categorize these {len(expenses)} transactions and give insights:\n{tx_lines}"

        print(f"Sending {len(expenses)} transactions to model for categorization...")
        completion = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            max_tokens=1024,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ]
        )

        raw_reply = completion.choices[0].message.content
        if not raw_reply or not raw_reply.strip():
            raise ValueError("Model returned an empty response. Please try again.")
        print(f"Model reply (first 400 chars): {raw_reply[:400]}")

        # ── Step 4: merge model categories into parsed transactions ──────────
        try:
            ai = extract_json(raw_reply)
        except Exception as parse_err:
            print(f"JSON parse failed: {parse_err}\nRaw: {raw_reply}")
            # Fall back: mark everything as 'other', still show correct totals
            ai = {}

        categories: list = ai.get("categories", [])
        for i, t in enumerate(expenses):
            cat = categories[i].lower().strip() if i < len(categories) else "shopping"
            t["category"] = cat if cat in CATEGORY_ORDER else "shopping"

        # ── Step 5: build result dict, compute ALL analytics server-side ─────
        result: dict = {
            "transactions": expenses,
            "credits": credits,
            "waste_score": int(ai.get("waste_score", 0)),
            "patterns": ai.get("patterns", []),
            "action_plan": ai.get("action_plan", []),
            # Everything below recalculated by compute_analytics:
            "total_spent": 0.0,
            "transaction_count": 0,
            "avg_transaction": 0.0,
            "top_category_name": "",
            "top_category_percent": "0%",
            "top_category_amount": 0.0,
            "subscriptions_total": 0.0,
            "subscriptions_count": 0,
            "donut": [0] * 8,
            "line_labels": [],
            "line_data": [],
        }

        result = compute_analytics(result, expenses)
        return jsonify({"response": json.dumps(result, ensure_ascii=False)})

    except Exception as e:
        error_msg = str(e)
        print(f"Error: {error_msg}")
        if "429" in error_msg:
            error_msg = "AI Concurrency Limit. Please wait 10 seconds and try again."
        return jsonify({"error": error_msg, "response": error_msg}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
