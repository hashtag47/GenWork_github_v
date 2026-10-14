import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.environ.get("REQUESTY_API_KEY"),
    base_url="https://router.requesty.ai/v1",
)

# send the test ping to the model
response = client.chat.completions.create(
    model="anthropic/claude-sonnet-5",
    messages=[
        {"role": "user", "content": "Say 'Gateway connection Successful'"},
    ],
    max_tokens=20
)

print(response.choices[0].message.content)