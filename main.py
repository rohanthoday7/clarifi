from flask import Flask, render_template, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# Initialize the OpenAI client with your Featherless setup
client = OpenAI(
    base_url="https://api.featherless.ai/v1",
    api_key="rc_655d9a938ab531ec296452a2dcf8d7e505a6f63009432109ced434a38cf3e4fd",
)

@app.route("/")
def home():
    # Serve the frontend HTML
    return render_template("index.html")

@app.route("/api/analyze", methods=["POST"])
def analyze_expenses():
    data = request.json
    user_prompt = data.get("prompt", "")
    
    try:
        # Run chat completions via Featherless
        chat_completions = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            max_tokens=4096,
            messages=[
                {"role": "system", "content": "You are a financial assistant called ClariFi. Provide a structured, short summary of the user's spending data. Do not use markdown backticks in your final output, keep it conversational but clear."},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        reply = chat_completions.choices[0].message.content
        return jsonify({"response": reply})
        
    except Exception as e:
        return jsonify({"error": str(e), "response": f"API Error: {str(e)}\n\n(Remember: You still need to enable API access on your Featherless subscription!)"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
