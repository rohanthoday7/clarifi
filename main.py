from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import requests
import os
import json
import re

app = Flask(__name__)

# Initialize the OpenAI client with your Featherless setup
client = OpenAI(
    base_url="https://api.featherless.ai/v1",
    api_key="rc_31cc85fe1260d49fca946c9cec89b488dfd4536e85e2b22f3edd2e8036ff2b0e",
)

# Initialize Bright Data variables
BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "YOUR_BRIGHTDATA_API_KEY")
BRIGHTDATA_ZONE = os.getenv("BRIGHTDATA_ZONE", "web_unlocker1")

CATEGORY_ORDER = ["food", "shopping", "transport", "subscriptions", "bills", "healthcare", "grocery", "fitness", "other"]


def extract_json(text):
    """
    Robustly extract a JSON object from raw AI output.
    Handles: markdown code fences, trailing commas, and extra text.
    """
    text = re.sub(r'```(?:json)?\s*', '', text).strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in AI response")
    json_str = text[start:end+1]
    # Clean up common AI JSON mistakes like trailing commas
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    return json.loads(json_str)


def fixup_analysis(data, transactions):
    """
    Server-side arithmetic enforcement to correct common model errors.
    Recalculates key fields directly from the parsed transactions list.
    """
    # --- Core stats from transactions ---
    expense_txns = [t for t in transactions if isinstance(t.get("amount"), (int, float)) and t["amount"] > 0]
    
    raw_total: float = float(sum(float(t["amount"]) for t in expense_txns))
    total_spent: float = int(raw_total * 100) / 100.0  # round to 2 dp
    tx_count = len(expense_txns)
    avg_tx: float = (int((total_spent / tx_count) * 100) / 100.0) if tx_count > 0 else 0.0

    data["total_spent"] = total_spent
    data["transaction_count"] = tx_count
    data["avg_transaction"] = avg_tx

    # --- Subscriptions ---
    sub_txns = [t for t in expense_txns if str(t.get("category", "")).lower() == "subscriptions"]
    data["subscriptions_total"] = int(float(sum(float(t["amount"]) for t in sub_txns)) * 100) / 100.0
    data["subscriptions_count"] = len(sub_txns)

    # --- Top category ---
    cat_totals = {}
    for t in expense_txns:
        cat = str(t.get("category", "other")).lower()
        cat_totals[cat] = cat_totals.get(cat, 0) + t["amount"]

    if cat_totals:
        top_cat = max(cat_totals, key=lambda k: cat_totals[k])
        top_amt = cat_totals[top_cat]
        top_pct = round((top_amt / total_spent) * 100) if total_spent > 0 else 0
        data["top_category_name"] = top_cat.title()
        data["top_category_amount"] = int(float(top_amt) * 100) / 100.0
        data["top_category_percent"] = f"{top_pct}%"
    else:
        data["top_category_name"] = "N/A"
        data["top_category_amount"] = 0
        data["top_category_percent"] = "0%"

    # --- Donut: recompute from scratch so it always sums to 100 ---
    donut = []
    if total_spent > 0:
        raw_pcts = []
        for cat in CATEGORY_ORDER:
            raw_pcts.append(cat_totals.get(cat, 0) / total_spent * 100)
        # Largest-remainder method for integer percentages summing to 100
        floors: list[int] = []
        remainders: list[tuple[float, int]] = []
        for idx, pct in enumerate(raw_pcts):
            f = int(pct)
            floors.append(f)
            remainders.append((pct - float(f), idx))
        floor_sum: int = int(sum(floors))
        remainder_needed: int = 100 - floor_sum
        remainders.sort(reverse=True)
        for i in range(remainder_needed):
            floors[remainders[i][1]] += 1
        donut = floors
    else:
        donut = [0] * 9

    data["donut"] = donut

    # --- Line chart: build from transaction dates if not provided well ---
    if not data.get("line_labels") or len(data.get("line_labels", [])) < 2:
        dated = [t for t in expense_txns if t.get("date")]
        dated.sort(key=lambda t: t.get("date", ""))
        # Group by date
        date_map = {}
        for t in dated:
            d = t["date"]
            date_map[d] = date_map.get(d, 0) + t["amount"]
        if date_map:
            data["line_labels"] = list(date_map.keys())
            data["line_data"] = [int(float(v) * 100) / 100.0 for v in date_map.values()]
        else:
            data["line_labels"] = ["Total"]
            data["line_data"] = [total_spent]

    return data


def scrape_with_brightdata(url):
    """Uses Bright Data Web Unlocker to bypass anti-bot systems and scrape the URL"""
    print(f"Scraping {url} via Bright Data...")
    response = requests.post(
        "https://api.brightdata.com/request",
        headers={
            "Authorization": f"Bearer {BRIGHTDATA_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "zone": BRIGHTDATA_ZONE,
            "url": url,
            "format": "raw",
        },
    )
    if response.status_code != 200:
        raise Exception(f"Bright Data Error {response.status_code}: {response.text}")
    return response.text


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze_expenses():
    body = request.json
    if not body:
        return jsonify({"error": "No JSON body received", "response": "No JSON body received"}), 400
    user_input = body.get("prompt", "")

    try:
        if user_input.startswith("http://") or user_input.startswith("https://"):
            scraped_html = scrape_with_brightdata(user_input)
            clipped_html = scraped_html[:3000]
            ai_prompt = f"I scraped a website. Extract all financial numbers/expenses from this raw website html:\n\n{clipped_html}"
        else:
            ai_prompt = user_input

        print("Sending to Featherless AI (Qwen 7B)...")

        system_instruction = """You are ClariFi, an expert financial analyst. Your ONLY job is to parse raw transaction text and return a single valid JSON object — nothing else. No explanation, no markdown, no preamble.

CATEGORIES (use only these exact strings, lowercase):
food, shopping, transport, subscriptions, bills, healthcare, grocery, fitness, other

INSTRUCTIONS:
1. Parse every transaction from the input text.
2. Ignore credits, income, salary, and refunds — do NOT include them in transactions[].
3. Put credits in the "credits" array instead.
4. The "transactions" array must contain EVERY expense you found.
5. For the "donut" field: 9 integers representing percentage of total spent per category (in order: food, shopping, transport, subscriptions, bills, healthcare, grocery, fitness, other). They MUST sum to exactly 100. If a category has no spending, use 0.
6. "waste_score": integer 0-100. Higher = more wasteful spending (e.g. luxury restaurants, impulse shopping).
7. "line_labels": dates (or merchant names if no dates) from the transactions, for a timeline chart.
8. "line_data": cumulative or per-day spend matching the line_labels array.
9. "patterns": 3 short bullet observations about the spending (e.g. "Heavy reliance on food delivery").
10. "action_plan": 3 actionable items with specific savings amounts.

RETURN ONLY THIS JSON (fill in real values):
{
  "total_spent": 0,
  "transaction_count": 0,
  "avg_transaction": 0,
  "top_category_name": "...",
  "top_category_percent": "0%",
  "top_category_amount": 0,
  "subscriptions_total": 0,
  "subscriptions_count": 0,
  "waste_score": 0,
  "donut": [0,0,0,0,0,0,0,0,0],
  "line_labels": [],
  "line_data": [],
  "transactions": [{"merchant": "...", "date": "...", "category": "...", "amount": 0}],
  "credits": [],
  "patterns": ["...", "...", "..."],
  "action_plan": [{"title": "...", "desc": "...", "saving": "..."}]
}"""

        chat_completions = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            max_tokens=4096,
            temperature=0.1,  # Low temperature for more deterministic, structured output
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": ai_prompt}
            ]
        )

        raw_reply = chat_completions.choices[0].message.content
        print(f"Raw AI reply (first 500 chars): {raw_reply[:500]}")

        try:
            parsed = extract_json(raw_reply)

            # Server-side arithmetic correction — never trust the model's math
            transactions = parsed.get("transactions", [])
            parsed = fixup_analysis(parsed, transactions)

            return jsonify({"response": json.dumps(parsed, ensure_ascii=False)})

        except Exception as parse_err:
            print(f"JSON extraction failed: {parse_err}")
            print(f"Full raw reply: {raw_reply}")
            return jsonify({
                "error": f"Could not parse AI response: {parse_err}",
                "response": raw_reply
            }), 500

    except Exception as e:
        error_msg = str(e)
        print(f"API error: {error_msg}")
        if "429" in error_msg:
            error_msg = "AI Concurrency Limit Exceeded. Please wait 10 seconds and try again."
        return jsonify({"error": error_msg, "response": error_msg}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
