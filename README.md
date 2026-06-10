# YouTube Quiz Generator

Generate UPSC-style multiple-choice quizzes from YouTube video transcripts using free LLM APIs (NVIDIA NIM). Works with videos in **any language** — quizzes are always generated in English.

## Quick Start

### 1. Set up environment

```powershell
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Set your NVIDIA NIM API key

1. Go to [https://build.nvidia.com](https://build.nvidia.com) (free)
2. Click **"Get API Key"** and copy it
3. Create a `.env` file:

```
NVIDIA_API_KEY=nvapi-your-key-here
```

### 3. Run the server

```powershell
python run_server.py
```

Open **http://localhost:8000** in your browser — that's the quiz-taking UI.

API docs at **http://localhost:8000/docs**

### Alternative: CLI mode

```powershell
python quiz_generator.py
```

Paste a YouTube URL, answer the prompts, take the quiz in your terminal.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/quiz/generate` | Generate quiz from YouTube URL |
| `POST` | `/api/quiz/submit` | Submit answers, get score |
| `GET` | `/api/video/{video_id}/languages` | List available caption languages |

### Example: Generate a quiz

```bash
curl -X POST http://localhost:8000/api/quiz/generate \
  -H "Content-Type: application/json" \
  -d '{"youtube_url": "https://www.youtube.com/watch?v=kFM72UJhW8s", "num_questions": 10, "difficulty": "moderate"}'
```

### Example: Submit answers

```bash
curl -X POST http://localhost:8000/api/quiz/submit \
  -H "Content-Type: application/json" \
  -d '{"quiz_id": "kFM72UJhW8s", "answers": [0, 2, 1, 3, 0]}'
```

## Project Structure

```
videos-to-quiz/
├── run_server.py                  # Start the FastAPI server
├── quiz_generator.py              # CLI entry point
├── requirements.txt
├── .env                           # NVIDIA API key (not in git)
├── .env.example
│
├── frontend/
│   └── index.html                 # Quiz-taking web UI
│
├── backend/app/
│   ├── main.py                    # FastAPI app + frontend serving
│   ├── models/
│   │   └── schemas.py             # Pydantic + dataclass models
│   ├── services/
│   │   ├── transcript.py          # YouTube transcript extraction
│   │   └── quiz_generator.py     # NVIDIA NIM quiz generation
│   └── routes/
│       ├── quiz.py                # /api/quiz/generate, /api/quiz/submit
│       └── video.py              # /api/video/{id}/languages
```

## Features

- **Any language video** — Hindi, Spanish, French, etc. Quizzes are always in English
- **UPSC-style questions** — Statement-based, assertion-reason, analytical formats
- **1-30 questions** — Batches API calls automatically for large quizzes
- **Auto-detect captions** — Prefers manual captions, falls back to auto-generated
- **Cloud deployment ready** — Invidious fallback bypasses YouTube's cloud IP blocking
- **Interactive web UI** — Paste a URL, take the quiz, see your score
- **Free LLM** — Uses NVIDIA NIM (Llama 3.3 70B), no paid API needed

## Transcript Fallback Strategy

YouTube blocks transcript requests from cloud/datacenter IPs (Render, Railway, AWS, etc.). The app handles this automatically with a multi-strategy fallback:

| Priority | Method | Works on cloud IPs? | Setup required? |
|----------|--------|---------------------|-----------------|
| 1 | youtube-transcript-api | ❌ Blocked on cloud | None |
| 2 | Cloudflare Worker proxy | ✅ CDN edge IPs | Deploy `cloudflare-worker.js` (free) |
| 3 | Invidious instances | ✅ Public proxies | None — works out of the box |
| 4 | yt-dlp | ⚠️ Sometimes | None |

**For local development**, strategy #1 works fine — no configuration needed.

**For Render/cloud deployments**, strategies #2 and #3 handle it automatically. Invidious (strategy #3) works out of the box with zero setup. For even more reliability, deploy `cloudflare-worker.js` to Cloudflare Workers (free tier: 100,000 requests/day) and set the `YOUTUBE_PROXY_URL` env var.

### Deploying the Cloudflare Worker (optional but recommended)

1. Create a free [Cloudflare account](https://dash.cloudflare.com/sign-up)
2. Go to **Workers & Pages → Create Application → Create Worker**
3. Paste the contents of `cloudflare-worker.js`
4. Deploy — you'll get a URL like `https://youtube-transcript-proxy.YOUR-NAME.workers.dev`
5. Set `YOUTUBE_PROXY_URL` on Render to that URL

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | Done | CLI script — transcript to quiz via NVIDIA NIM |
| **Phase 2** | Done | FastAPI backend with REST API |
| **Phase 3** | Done | Web UI for quiz-taking |
| **Phase 4** | Next | Polish, auth, database, deploy |

## License

MIT