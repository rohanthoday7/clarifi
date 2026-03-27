from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import requests
import os

app = Flask(__name__)

# Initialize the OpenAI client with your Featherless setup
client = OpenAI(
    base_url="https://api.featherless.ai/v1",
    api_key="rc_31cc85fe1260d49fca946c9cec89b488dfd4536e85e2b22f3edd2e8036ff2b0e",
)

# Initialize Bright Data variables (from the ScrapeAlchemist Hack-Pack)
BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "YOUR_BRIGHTDATA_API_KEY")
BRIGHTDATA_ZONE = os.getenv("BRIGHTDATA_ZONE", "web_unlocker1")

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
    # Serve the frontend HTML
    return render_template("index.html")

@app.route("/api/analyze", methods=["POST"])
def analyze_expenses():
    data = request.json
    user_input = data.get("prompt", "")
    
    try:
        # Check if the user pasted a URL instead of text
        if user_input.startswith("http://") or user_input.startswith("https://"):
            scraped_html = scrape_with_brightdata(user_input)
            
            # Use the first 3000 chars of the website to avoid exceeding the AI's memory limit
            clipped_html = scraped_html[:3000]
            ai_prompt = f"I scraped a website. Extract all financial numbers/expenses from this raw website html:\n\n{clipped_html}"
        else:
            ai_prompt = user_input

        # Run chat completions via Featherless
        print("Sending to Featherless AI...")
        system_instruction = """You are ClariFi, an expert expense analyzer. Every time a user pastes transaction data, automatically generate a full analysis. Return ONLY a single raw valid JSON object — no markdown, no backticks, no intro text.

Categories to use:
- food (Swiggy, Zomato, Starbucks, Restaurant, food delivery)
- shopping (Amazon, Flipkart, Myntra, Zara, retail)
- transport (Uber, Ola, Petrol, Bus, auto)
- subscriptions (Netflix, Spotify, Apple Music, Prime, any subscription)
- bills (Electricity, Recharge, phone bill, broadband)
- healthcare (Medical store, pharmacy, doctor, hospital)
- grocery (Grocery, supermarket, BigBasket, DMart)
- fitness (Gym, yoga, sports)
- other (anything else)

CRITICAL: skip credits/income (UPI received, salary, refunds) from totals but include them in credits array.

JSON Schema to return:
{
  "thinking_process": "scratchpad: list each line item, assign category and amount, sum per category, compute percentages",
  "total_spent": 0,
  "transaction_count": 0,
  "avg_transaction": 0,
  "top_category_name": "Shopping",
  "top_category_percent": "35%",
  "top_category_amount": 0,
  "subscriptions_total": 0,
  "subscriptions_count": 0,
  "waste_score": 42,
  "donut": [20, 35, 10, 5, 10, 5, 10, 5, 0],
  "line_labels": ["Jul 12", "Jul 13"],
  "line_data": [500, 1200],
  "transactions": [
    {"merchant": "Swiggy", "date": "Jul 12", "category": "food", "amount": 450}
  ],
  "credits": [
    {"source": "UPI from Rahul", "date": "Jul 15", "amount": 500}
  ],
  "category_breakdown": [
    {"name": "Food & Dining", "key": "food", "amount": 0, "percent": "0%"},
    {"name": "Shopping", "key": "shopping", "amount": 0, "percent": "0%"},
    {"name": "Transport", "key": "transport", "amount": 0, "percent": "0%"},
    {"name": "Subscriptions", "key": "subscriptions", "amount": 0, "percent": "0%"},
    {"name": "Bills & Utilities", "key": "bills", "amount": 0, "percent": "0%"},
    {"name": "Healthcare", "key": "healthcare", "amount": 0, "percent": "0%"},
    {"name": "Grocery", "key": "grocery", "amount": 0, "percent": "0%"},
    {"name": "Fitness", "key": "fitness", "amount": 0, "percent": "0%"},
    {"name": "Other", "key": "other", "amount": 0, "percent": "0%"}
  ],
  "patterns": [
    "Food delivery 3x in 7 days — ₹1,120 total",
    "Duplicate streaming subscriptions detected",
    "Impulse shopping spike of ₹4,499 on Jul 14"
  ],
  "action_plan": [
    {"title": "Cancel duplicate streaming sub", "desc": "You pay for both Netflix and Spotify. Cancel one to save ₹499/mo.", "saving": "₹5,988/yr"},
    {"title": "Set weekly food delivery cap", "desc": "3 orders in 7 days at ₹1,120. Cap at ₹600/week by cooking 2 meals at home.", "saving": "₹2,500/mo"},
    {"title": "Review impulse shopping", "desc": "₹4,499 Amazon + Flipkart spike on one day. Add items to cart and wait 24hrs before buying.", "saving": "₹3,000/mo"}
  ]
}

RULES:
1. thinking_process must be first. Use it to enumerate every line item and do the math.
2. donut = 9 integers [food, shopping, transport, subscriptions, bills, healthcare, grocery, fitness, other] summing to 100.
3. line_labels = unique dates; line_data = total expenses per date (no credits).
4. waste_score: 0–25 = efficient, 26–50 = moderate, 51–75 = wasteful, 76–100 = very wasteful. Base on food delivery frequency, duplicate subs, impulse spikes, small discretionary habits.
5. All amounts must EXACTLY match the user's data. No invented numbers. Raw JSON only."""
        
        chat_completions = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": ai_prompt}
            ]
        )
        
        reply = chat_completions.choices[0].message.content
        return jsonify({"response": reply})
        
    except Exception as e:
        return jsonify({"error": str(e), "response": f"System Error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
