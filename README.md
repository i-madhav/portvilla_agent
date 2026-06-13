# Portvilla Agent

Voice agent worker for the Portvilla developer portfolio platform.
Built with [LiveKit Agents](https://github.com/livekit/agents) v1.0+.

## Setup

1. Copy `.env.example` to `.env.local` and fill in your credentials:

```
LIVEKIT_URL=wss://your-livekit-instance.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
BACKEND_URL=http://localhost:3000/api/v1
```

2. Install dependencies:

```bash
uv sync
```

3. Download model files (VAD, turn detector):

```bash
uv run python -m agent.main download-files
```

## Running

Test locally in the terminal (no frontend needed):

```bash
uv run python -m agent.main console
```

Run against the frontend:

```bash
uv run python -m agent.main dev
```

Run in production:

```bash
uv run python -m agent.main start
```
