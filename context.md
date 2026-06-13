# Portvilla Agent — Claude Code Context

## What This Is

This is the voice agent worker for **Portvilla** — a developer portfolio platform where an AI agent
represents a developer and can have real conversations with visitors about their skills, projects,
and experience. Think of it as an AI-powered "talk to me" button on a developer's portfolio.

The agent is a **standalone Python process** using the LiveKit Agents SDK (v1.0+).
It is NOT a web server. It connects to LiveKit as a worker, waits for visitors to join a room,
and handles the full STT → LLM → TTS voice conversation pipeline.

---

## How It Fits In The Broader System

```
portvilla-BE  (NestJS)          portvilla-agent  (this repo)        portvilla-FE  (React)
──────────────────────          ────────────────────────────         ──────────────────────
POST /agent/token           ←── (visitor requests token)       ←──  visitor clicks "talk"
GET  /agent/context/:user   ←── agent fetches on room join           
                                                                ←──  LiveKit audio  (voice)
                                agent ──────────────────────►       LiveKit data channel (UI commands)
```

The **NestJS backend** owns: auth, profiles, GitHub parsing, token issuance, portfolio context serving.
The **agent worker** owns: the voice conversation, deciding what to say, deciding what UI to show.
The **frontend** owns: rendering the orb, animating transitions, rendering content panels.

---

## The Core UX Behaviour

A visitor lands on a developer's Portvilla page and sees a **fullscreen animated orb**.
They click/speak to start the conversation. As the conversation progresses:

- If the visitor asks about projects → orb moves to **bottom-right PIP**, a project card slides in
- If the visitor asks about skills → orb stays PIP, a tech stack grid appears
- If the visitor asks about experience → a timeline/experience card appears
- If conversation returns to general topics → orb returns to fullscreen

**Key timing rule**: tool calls fire *before* TTS audio starts.
The TTS conversion latency (~200–400 ms) is the natural window to animate the UI.
By the time the agent's voice plays, the correct UI panel is already visible.

---

## Tech Stack & SDK Version

- **Language**: Python 3.11+
- **Package manager**: `uv` (NOT pip)
- **Agent framework**: `livekit-agents>=1.0` — uses the NEW API (`Agent`, `AgentSession`, `@function_tool`)
- **STT**: Deepgram via LiveKit Inference (`inference.STT`)
- **LLM**: OpenAI-compatible via LiveKit Inference (`inference.LLM`) — model is configurable
- **TTS**: Cartesia or ElevenLabs via LiveKit Inference (`inference.TTS`)
- **VAD**: Silero (`livekit-plugins-silero`)
- **HTTP client**: `httpx` (async) for calling the NestJS backend
- **Config**: `python-dotenv`

### Critical: New v1.0 API — do NOT use the old patterns

| Old (v0.8, DO NOT USE)         | New (v1.0+, USE THIS)                        |
|-------------------------------|----------------------------------------------|
| `VoicePipelineAgent`          | `AgentSession` + `Agent` subclass            |
| `llm.FunctionContext`         | Methods on `Agent` with `@function_tool`     |
| `@llm.ai_callable`            | `@function_tool` from `livekit.agents.llm`   |
| Tools as a separate class     | Tools as methods on the `Agent` subclass     |
| `WorkerOptions(entrypoint_fnc)` | Same — still valid in v1.0               |

---

## Project Structure

```
portvilla-agent/
├── context.md                  ← this file
├── .env.local                  ← secrets (not committed)
├── .env.example
├── pyproject.toml
├── agent/
│   ├── __init__.py
│   ├── main.py                 ← entrypoint — WorkerOptions + cli.run_app
│   ├── assistant.py            ← PortvillaAssistant(Agent) class + all @function_tool methods
│   ├── ui_commands.py          ← UICommand types + publish_data emitter
│   ├── context.py              ← fetch_portfolio_context() using httpx
│   └── prompts.py              ← build_system_prompt() → str
```

Note: tools live on the `PortvillaAssistant` class in `assistant.py` (not a separate file),
because `@function_tool` methods must be on the `Agent` subclass in v1.0.

---

## Environment Variables

STT, LLM, and TTS all route through **LiveKit Inference** — no provider API keys needed.
Only LiveKit credentials and the backend URL are required.

```env
# LiveKit (all inference is billed through this account)
LIVEKIT_URL=wss://your-livekit-instance.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret

# NestJS backend
BACKEND_URL=http://localhost:3000/api/v1
```

Model and voice choices are hardcoded in the agent (see Main Entrypoint).
The TTS voice per user comes from `portfolio.voice_id` fetched from the backend.

---

## Portfolio Context Shape

When the agent joins a room it calls `GET {BACKEND_URL}/agent/context/{username}`.
The backend returns JSON. Parse it into these dataclasses:

```python
from dataclasses import dataclass, field

@dataclass
class Project:
    name: str
    url: str | None
    description: str
    technologies: list[str]

@dataclass
class Repository:
    name: str
    full_name: str
    url: str
    description: str | None
    language: str | None
    frameworks: list[str]
    detected_tools: list[str]
    readme: str | None      # truncate to 500 chars when building prompt

@dataclass
class PortfolioContext:
    username: str
    name: str
    title: str
    about_me: str
    introduction: str
    skills: list[str]
    technologies: list[str]
    current_position: dict | None
    experience: list[dict]  # [{title, company, startDate, endDate, description}]
    education: list[dict]
    projects: list[Project]
    top_repositories: list[Repository]
    github_username: str | None
    linkedin: str | None
    personal_website: str | None
    agent_name: str          # e.g. "Alex"
    agent_tone: str          # "formal" | "balanced" | "casual"
    agent_verbosity: str     # "concise" | "detailed"
    technical_depth: str     # "high" | "medium" | "low"
    voice_id: str | None     # TTS voice ID
```

The room name carries the portfolio owner's username: `"portvilla-{username}"`.
Read it with `ctx.room.name.removeprefix("portvilla-")`.

---

## Session UserData

State shared between the entrypoint and tool calls is stored in a typed userdata dataclass:

```python
from dataclasses import dataclass
from livekit import agents

@dataclass
class AppUserData:
    ctx: agents.JobContext        # stored so tools can access ctx.room
    portfolio: PortfolioContext   # the fetched portfolio, used in tools
```

Pass it when creating `AgentSession`:

```python
session = AgentSession[AppUserData](
    userdata=AppUserData(ctx=ctx, portfolio=portfolio),
    stt=..., llm=..., tts=..., vad=...,
)
```

Access it in tool methods via `context.userdata`:

```python
@function_tool
async def show_project(self, context: RunContext[AppUserData], project_name: str) -> str:
    room = context.userdata.ctx.room
    portfolio = context.userdata.portfolio
    ...
```

---

## UICommand Protocol

Commands are broadcast as JSON over LiveKit's data channel.
The frontend listens to the `"ui-command"` topic and updates the UI state machine.

```python
# agent/ui_commands.py

from dataclasses import dataclass, asdict
from enum import Enum
import json
from livekit import rtc

class UICommandType(str, Enum):
    ORB_FULLSCREEN  = "ORB_FULLSCREEN"   # orb takes full screen
    ORB_TO_PIP      = "ORB_TO_PIP"       # orb moves to bottom-right corner
    SHOW_PROJECT    = "SHOW_PROJECT"
    SHOW_TECH_STACK = "SHOW_TECH_STACK"
    SHOW_GITHUB     = "SHOW_GITHUB"
    SHOW_EXPERIENCE = "SHOW_EXPERIENCE"
    CLEAR_CONTENT   = "CLEAR_CONTENT"

UI_COMMAND_TOPIC = "ui-command"

async def emit_ui_command(
    room: rtc.Room,
    command_type: UICommandType,
    payload: dict | None = None,
) -> None:
    message: dict = {"type": command_type.value}
    if payload:
        message["payload"] = payload
    await room.local_participant.publish_data(
        json.dumps(message).encode("utf-8"),
        reliable=True,
        topic=UI_COMMAND_TOPIC,
    )
```

Payload shapes:

```python
@dataclass
class ShowProjectPayload:
    name: str
    description: str
    url: str | None
    tech_stack: list[str]
    preview_image_url: str | None = None

@dataclass
class ShowTechStackPayload:
    technologies: list[dict]  # [{"name": "React", "category": "frontend"}]

@dataclass
class ShowGithubPayload:
    username: str
    top_repos: list[str]
    languages: list[str]

@dataclass
class ShowExperiencePayload:
    company: str
    role: str
    period: str
    description: str
```

---

## Agent Class & Tool Definitions

All tools are `@function_tool` methods on the `PortvillaAssistant` class.
Access the room and portfolio through `context.userdata`.

```python
# agent/assistant.py

import logging
from livekit.agents import Agent
from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext
from .ui_commands import emit_ui_command, UICommandType, ShowProjectPayload, \
    ShowTechStackPayload, ShowGithubPayload, ShowExperiencePayload
from .context import PortfolioContext, AppUserData
from .prompts import build_system_prompt
import dataclasses

logger = logging.getLogger("portvilla.assistant")


class PortvillaAssistant(Agent):
    def __init__(self, portfolio: PortfolioContext) -> None:
        super().__init__(
            instructions=build_system_prompt(portfolio),
        )
        self._portfolio = portfolio

    @function_tool
    async def show_project(self, context: RunContext[AppUserData], project_name: str) -> str:
        """Show a project card in the UI. Call this whenever you are about to describe
        a specific project. The card appears before you start speaking about it.

        Args:
            project_name: The name of the project to display.
        """
        room = context.userdata.ctx.room
        project = next(
            (p for p in self._portfolio.projects
             if p.name.lower() == project_name.lower()),
            None,
        )
        if not project:
            # fallback: try partial match
            project = next(
                (p for p in self._portfolio.projects
                 if project_name.lower() in p.name.lower()),
                None,
            )
        if project:
            await emit_ui_command(room, UICommandType.ORB_TO_PIP)
            await emit_ui_command(room, UICommandType.SHOW_PROJECT, dataclasses.asdict(
                ShowProjectPayload(
                    name=project.name,
                    description=project.description,
                    url=project.url,
                    tech_stack=project.technologies,
                )
            ))
        return f"Showing project: {project.name if project else project_name}."

    @function_tool
    async def show_tech_stack(self, context: RunContext[AppUserData]) -> str:
        """Show the skills and tech stack grid. Call this when the visitor asks
        about technical skills, technologies, or what the developer knows.
        """
        room = context.userdata.ctx.room
        techs = [
            {"name": t, "category": "skill"}
            for t in self._portfolio.technologies
        ]
        await emit_ui_command(room, UICommandType.ORB_TO_PIP)
        await emit_ui_command(room, UICommandType.SHOW_TECH_STACK, dataclasses.asdict(
            ShowTechStackPayload(technologies=techs)
        ))
        return "Showing tech stack."

    @function_tool
    async def show_github(self, context: RunContext[AppUserData]) -> str:
        """Show GitHub stats and top repositories. Call this when the visitor asks
        about open source work, GitHub activity, or wants to browse code.
        """
        if not self._portfolio.github_username:
            return "No GitHub profile linked."
        room = context.userdata.ctx.room
        languages = list({
            r.language for r in self._portfolio.top_repositories if r.language
        })
        await emit_ui_command(room, UICommandType.ORB_TO_PIP)
        await emit_ui_command(room, UICommandType.SHOW_GITHUB, dataclasses.asdict(
            ShowGithubPayload(
                username=self._portfolio.github_username,
                top_repos=[r.name for r in self._portfolio.top_repositories[:5]],
                languages=languages,
            )
        ))
        return "Showing GitHub profile."

    @function_tool
    async def show_experience(self, context: RunContext[AppUserData], company: str) -> str:
        """Show a work experience card. Call this when discussing a specific role or company.

        Args:
            company: The company name to display experience for.
        """
        room = context.userdata.ctx.room
        exp = next(
            (e for e in self._portfolio.experience
             if company.lower() in e.get("company", "").lower()),
            None,
        )
        if exp:
            await emit_ui_command(room, UICommandType.ORB_TO_PIP)
            await emit_ui_command(room, UICommandType.SHOW_EXPERIENCE, dataclasses.asdict(
                ShowExperiencePayload(
                    company=exp["company"],
                    role=exp["title"],
                    period=f"{exp['startDate']} – {exp.get('endDate', 'Present')}",
                    description=exp.get("description", ""),
                )
            ))
        return f"Showing experience at {company}."

    @function_tool
    async def return_to_orb(self, context: RunContext[AppUserData]) -> str:
        """Return the orb to fullscreen and clear displayed content.
        Call this when the conversation moves to a general topic with nothing specific to show.
        """
        room = context.userdata.ctx.room
        await emit_ui_command(room, UICommandType.CLEAR_CONTENT)
        await emit_ui_command(room, UICommandType.ORB_FULLSCREEN)
        return "Returning to orb."
```

---

## System Prompt Builder

```python
# agent/prompts.py

from .context import PortfolioContext

def build_system_prompt(portfolio: PortfolioContext) -> str:
    tone_map = {
        "formal": "professional and formal",
        "balanced": "friendly but professional",
        "casual": "casual and conversational",
    }
    depth_map = {
        "high": "go deep on technical details when asked",
        "medium": "balance technical and non-technical explanations",
        "low": "keep explanations accessible, avoid jargon",
    }

    projects_text = "\n".join(
        f"- {p.name}: {p.description} (tech: {', '.join(p.technologies)})"
        for p in portfolio.projects
    ) or "No projects listed."

    repos_text = "\n".join(
        f"- {r.name} ({r.language or 'unknown'}): {', '.join(r.frameworks)}"
        for r in portfolio.top_repositories[:5]
    ) or "No repositories."

    current = portfolio.current_position
    position_text = (
        f"{current['title']} at {current['company']}" if current else "Not specified."
    )

    verbosity_note = (
        "Keep answers concise — 2 to 3 sentences max unless asked for more."
        if portfolio.agent_verbosity == "concise"
        else "Feel free to give detailed, thorough answers."
    )

    return f"""You are {portfolio.agent_name}, an AI agent representing {portfolio.name}.
Your job is to have a natural voice conversation with visitors about {portfolio.name}'s
background, skills, projects, and experience.

Tone: {tone_map.get(portfolio.agent_tone, "friendly but professional")}
Technical depth: {depth_map.get(portfolio.technical_depth, "balanced")}
{verbosity_note}

--- About {portfolio.name} ---
Title: {portfolio.title}
Current position: {position_text}
Introduction: {portfolio.introduction}
About: {portfolio.about_me}
Skills: {", ".join(portfolio.skills) or "Not listed."}
Technologies: {", ".join(portfolio.technologies) or "Not listed."}

--- Projects ---
{projects_text}

--- GitHub Repositories ---
{repos_text}

--- Important Rules ---
- You are speaking *on behalf of* {portfolio.name}, not *as* them.
  Use "{portfolio.name}" or "they/their" — not "I/my" — unless the instructions say first-person.
- When you mention a project or skill, IMMEDIATELY call the matching display tool BEFORE
  you start describing it. The UI card must appear as you speak.
- Never invent details not present in the context above.
- End each turn with a natural follow-up question or an invitation to ask more.
- You are a voice agent — avoid markdown, bullet points, lists, or any formatting.
  Speak in plain, natural sentences only.
"""
```

---

## Context Fetcher

```python
# agent/context.py

import os
import logging
import httpx
from dataclasses import dataclass, field
from livekit import agents

logger = logging.getLogger("portvilla.context")

@dataclass
class Project:
    name: str
    url: str | None
    description: str
    technologies: list[str]

@dataclass
class Repository:
    name: str
    full_name: str
    url: str
    description: str | None
    language: str | None
    frameworks: list[str]
    detected_tools: list[str]
    readme: str | None

@dataclass
class PortfolioContext:
    username: str
    name: str
    title: str
    about_me: str
    introduction: str
    skills: list[str]
    technologies: list[str]
    current_position: dict | None
    experience: list[dict]
    education: list[dict]
    projects: list[Project]
    top_repositories: list[Repository]
    github_username: str | None
    linkedin: str | None
    personal_website: str | None
    agent_name: str
    agent_tone: str
    agent_verbosity: str
    technical_depth: str
    voice_id: str | None

@dataclass
class AppUserData:
    ctx: agents.JobContext
    portfolio: PortfolioContext


async def fetch_portfolio_context(username: str) -> PortfolioContext:
    backend_url = os.environ["BACKEND_URL"]
    url = f"{backend_url}/agent/context/{username}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    projects = [
        Project(
            name=p["name"],
            url=p.get("url"),
            description=p.get("description", ""),
            technologies=p.get("technologies", []),
        )
        for p in data.get("projects", [])
    ]

    repositories = [
        Repository(
            name=r["name"],
            full_name=r["fullName"],
            url=r["url"],
            description=r.get("description"),
            language=r.get("language"),
            frameworks=r.get("insights", {}).get("frameworks", []),
            detected_tools=r.get("insights", {}).get("detectedTools", []),
            readme=(r.get("insights", {}).get("readme") or "")[:500] or None,
        )
        for r in data.get("topRepositories", [])
    ]

    return PortfolioContext(
        username=data["username"],
        name=data["name"],
        title=data.get("title", ""),
        about_me=data.get("aboutMe", ""),
        introduction=data.get("introduction", ""),
        skills=data.get("skills", []),
        technologies=data.get("technologies", []),
        current_position=data.get("currentPosition"),
        experience=data.get("experience", []),
        education=data.get("education", []),
        projects=projects,
        top_repositories=repositories,
        github_username=data.get("githubUsername"),
        linkedin=data.get("linkedin"),
        personal_website=data.get("personalWebsite"),
        agent_name=data.get("agentName", "Alex"),
        agent_tone=data.get("agentTone", "balanced"),
        agent_verbosity=data.get("agentVerbosity", "concise"),
        technical_depth=data.get("technicalDepth", "medium"),
        voice_id=data.get("voiceId"),
    )
```

---

## Main Entrypoint

```python
# agent/main.py

import asyncio
import logging
from dotenv import load_dotenv
from pathlib import Path
from livekit import agents
from livekit.agents import JobContext, WorkerOptions, cli, inference
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .context import fetch_portfolio_context, AppUserData
from .assistant import PortvillaAssistant

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env.local")

logger = logging.getLogger("portvilla")

# Platform-level model choices — not per-user, not in env vars
STT_MODEL = "deepgram/nova-3"
LLM_MODEL = "openai/gpt-4o-mini"
TTS_MODEL = "cartesia/sonic-2"
DEFAULT_TTS_VOICE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"  # fallback voice


def prewarm(proc: agents.JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    username = ctx.room.name.removeprefix("portvilla-")
    logger.info("Starting session for portfolio: %s", username)

    try:
        portfolio = await fetch_portfolio_context(username)
    except Exception as exc:
        logger.error("Failed to fetch portfolio context: %s", exc)
        session = agents.voice.AgentSession(
            llm=inference.LLM(model=LLM_MODEL),
        )
        await session.start(room=ctx.room, agent=agents.Agent(
            instructions="Tell the user briefly that the portfolio could not be loaded and apologise."
        ))
        await asyncio.sleep(5)
        return

    session = agents.voice.AgentSession[AppUserData](
        userdata=AppUserData(ctx=ctx, portfolio=portfolio),
        stt=inference.STT(model=STT_MODEL, language="multi"),
        llm=inference.LLM(model=LLM_MODEL),
        tts=inference.TTS(model=TTS_MODEL, voice=portfolio.voice_id or DEFAULT_TTS_VOICE),
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
        preemptive_generation=True,
    )

    await session.start(
        room=ctx.room,
        agent=PortvillaAssistant(portfolio=portfolio),
    )

    greeting = (
        f"Hi! I'm {portfolio.agent_name}, here to tell you about "
        f"{portfolio.name}'s work and experience. What would you like to know?"
    )
    await session.generate_reply(instructions=greeting)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
```

---

## pyproject.toml

```toml
[project]
name = "portvilla-agent"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "livekit-agents[inference,silero,turn-detector]>=1.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
]

# inference extra covers STT + LLM + TTS via LiveKit Inference — no provider API keys needed
# silero is needed for VAD (runs locally)
# turn-detector is needed for MultilingualModel
```

---

## What Claude Code Should Generate

1. All files in the structure above as complete, working Python code
2. `.env.example` with all variables from the Environment Variables section
3. `.env.local` as an empty file (gitignored) — user fills it in
4. `agent/__init__.py` — empty
5. A `README.md` with setup:
   ```
   uv sync
   uv run python -m agent.main download-files
   uv run python -m agent.main console      # test locally in terminal
   uv run python -m agent.main dev          # run for frontend use
   ```
6. `.gitignore` — ignore `.env.local`, `__pycache__`, `.venv`
7. Logging: use `logging.getLogger("portvilla.<module>")` throughout — no print statements
8. Type hints on all functions

## Do NOT generate

- Any web server, HTTP routes, or FastAPI/Flask app
- Any database connections (all data comes from the NestJS backend)
- Any authentication logic (tokens are issued by NestJS)
- Tests
- The NestJS `/agent/context/:username` endpoint itself — that is built separately in portvilla-BE
