from openai import OpenAI

# Initialize the OpenAI client with your Featherless setup
client = OpenAI(
    base_url="https://api.featherless.ai/v1",
    api_key="rc_655d9a938ab531ec296452a2dcf8d7e505a6f63009432109ced434a38cf3e4fd",
)

def main():
    try:
        # Run your chat completions
        chat_completions = client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            max_tokens=4096,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is the fastest way to get to the airport?"}
            ]
        )
        
        for choice in chat_completions.choices:
            print(choice.message.content)
            
    except Exception as e:
        print("Error generating completion:", e)

if __name__ == "__main__":
    main()
