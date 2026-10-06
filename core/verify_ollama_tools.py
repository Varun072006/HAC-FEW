"""
Verification script for Ollama connectivity and structured tool calling.
Tests:
1. Local Ollama server ping (default port 11434)
2. Model availability check (llama3.1:8b, llama3, or qwen2.5)
3. Structured output / tool-calling format test
"""
import json
import urllib.request
import urllib.error

OLLAMA_HOST = "http://localhost:11434"

def check_ollama_server():
    print(f"[*] Checking Ollama connectivity at {OLLAMA_HOST}...")
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                models = [m["name"] for m in data.get("models", [])]
                print(f"[+] Ollama is online! Available models: {models}")
                return models
    except Exception as e:
        print(f"[-] Could not reach Ollama: {e}")
        return []

def test_tool_calling(model_name: str):
    print(f"\n[*] Testing structured JSON generation with model '{model_name}'...")
    prompt = (
        "Classify the following enterprise request into a JSON object with keys: "
        "'agent' (one of: hr, finance, it), 'action', 'risk_level' (low, medium, high).\n"
        "Request: 'Provision a new developer MacBook Pro for our incoming software engineer.'\n"
        "Return ONLY the valid JSON object."
    )
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    
    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            response_text = result.get("response", "").strip()
            print("[+] Model raw response:\n", response_text)
            parsed = json.loads(response_text)
            print("[+] Successfully parsed JSON output:", parsed)
            print("[+] Tool-calling test PASSED!")
            return True
    except Exception as e:
        print(f"[-] Tool-calling test failed: {e}")
        return False

if __name__ == "__main__":
    models = check_ollama_server()
    if models:
        # Prefer llama3.1:8b if present, else test whatever model is available
        selected_model = "llama3.1:8b" if "llama3.1:8b" in models else ("llama3:latest" if "llama3:latest" in models else models[0])
        print(f"[*] Selected model for test: {selected_model}")
        test_tool_calling(selected_model)
    else:
        print("[-] Please ensure Ollama is running (`ollama serve`).")
