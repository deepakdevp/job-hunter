# LLM Providers

Job Hunter supports four LLM providers. Set your choice in `~/.config/job-hunter/.env`:

```bash
LLM_PROVIDER=gemini    # gemini | openai | claude | ollama
LLM_MODEL=gemini-2.5-flash
```

## Gemini (recommended)

Google's Gemini models. Generous free tier, good for scoring and tailoring.

1. Go to [AI Studio](https://aistudio.google.com/apikey)
2. Click "Create API key"
3. Add to `.env`:

```bash
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
GEMINI_API_KEY=your-key-here
```

Install the SDK:

```bash
pip install -e ".[gemini]"
```

## OpenAI

GPT-4o and GPT-4o-mini from OpenAI.

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new secret key
3. Add to `.env`:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-your-key-here
```

Install the SDK:

```bash
pip install -e ".[openai]"
```

## Claude

Anthropic's Claude models.

1. Go to [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
2. Create a new API key
3. Add to `.env`:

```bash
LLM_PROVIDER=claude
LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Install the SDK:

```bash
pip install -e ".[claude]"
```

## Ollama (local, free)

Run models locally with no API key and no cost.

1. Install Ollama:

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

2. Start the server and pull a model:

```bash
ollama serve &
ollama pull llama3.1
```

3. Add to `.env`:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
```

No SDK install needed -- Ollama uses a local HTTP API.

## Switching Providers

Change `LLM_PROVIDER` and `LLM_MODEL` in `.env` at any time. The factory in `llm/base.py` lazy-imports only the SDK you need, so unused providers do not need to be installed.

## Verify Setup

```bash
hunt doctor
```

This checks that your chosen LLM SDK is importable and your config files exist.
