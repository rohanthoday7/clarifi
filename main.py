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
        system_instruction = """You are a financial assistant named ClariFi. 
You must analyze the user's input expenses and return ONLY raw, valid JSON. YOU MUST CALCULATE ACCURATE NUMBERS purely based on the user's input. Do NOT copy the sample data from this prompt.

Format to strictly follow:
{
  "thinking_process": "Write out your step-by-step logic and calculation scratchpad here. Add up the expenses, assign categories, and do the percentages math CAREFULLY before filling out the rest of the JSON.",
  "total_spent": 1234,
  "transaction_count": 3,
  "top_category_name": "Food & Dining",
  "top_category_percent": "50%",
  "top_category_amount": 617,
  "subscriptions_total": 0,
  "subscriptions_count": 0,
  "donut": [50, 20, 0, 10, 20], 
  "line_labels": ["Jul 12", "Jul 13", "Jul 14"],
  "line_data": [450, 0, 784]
}

CRITICAL RULES:
1. `thinking_process` must be the very first key. Use it to map out the math before answering!
2. `donut` array MUST contain exactly 5 integer percentages [Food, Shopping, Subscriptions, Transport, Other] that sum to 100.
3. `line_labels` must be the unique dates found in the text.
4. `line_data` must be the math sum of all expenses spent on each corresponding date in line_labels.
5. If the text has no expenses, return zeroes. Output raw JSON object only. No intro."""
        
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
