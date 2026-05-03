import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env
# This assumes the .env file is in the project root (one level up from this file)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

def test_openai_connection():
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    
    print("--- OpenAI Connection Test ---")
    print(f"API Key: {api_key}")
    print(f"Base URL: {base_url}")
    
    # Initialize the OpenAI client
    # If base_url is set, it will point to your local proxy (LiteLLM)
    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )
    
    try:
        print("\nFetching available models from proxy...")
        models = client.models.list()
        print("Available models:")
        for m in models.data:
            print(f" - {m.id}")
            
        # Try using 'gpt-api' which is defined in config.yaml
        target_model = "gpt-api"
        print(f"\nSending 'Hello' prompt to model '{target_model}'...")
        
        response = client.chat.completions.create(
            model=target_model, 
            messages=[
                {"role": "user", "content": "Hello"}
            ],
            max_tokens=20
        )
        
        print("\n✅ Success! Response received:")
        print(f"Model: {response.model}")
        print(f"Message: {response.choices[0].message.content.strip()}")
        
        # Test embeddings
        embed_model = "text-embedding-3-small"
        print(f"\nTesting embeddings with model '{embed_model}'...")
        embed_response = client.embeddings.create(
            model=embed_model,
            input="Hello world"
        )
        print("✅ Success! Embedding received.")
        print(f"Vector length: {len(embed_response.data[0].embedding)}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nPossible reasons:")
        print("1. Your local proxy (LiteLLM) at localhost:4000 is not running.")
        print("2. The OPENAI_API_KEY is invalid for the configured provider.")
        print("3. The model 'gpt-api' is not recognized by the proxy.")

if __name__ == "__main__":
    test_openai_connection()
