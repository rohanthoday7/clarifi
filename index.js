const { OpenAI } = require("openai");

// Load the environment variables or insert your keys directly (though env vars are recommended)
const recursalApiKey = process.env.RECURSAL_API_KEY || "YOUR_RECURSAL_API_KEY";

// 2. Configure the SDK Client for Recursal
const openai = new OpenAI({
  apiKey: recursalApiKey,
  baseURL: "https://api.recursal.ai/v1", // Using the Recursal Base URL. Update if they have a different specific endpoint
});

// 3. Run your completions
async function main() {
  try {
    const completion = await openai.chat.completions.create({
      model: "Qwen/Qwen2.5-7B-Instruct",
      messages: [
        { role: "system", content: "You are a helpful assistant." },
        { role: "user", content: "Tell me a fun fact about space." }
      ],
    });

    console.log("Response:", completion.choices[0].message.content);
  } catch (error) {
    console.error("Error generating completion:", error);
  }
}

main();
