import os
import logging
import httpx
from dataclasses import dataclass
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


def fallback_portfolio_context(username: str) -> PortfolioContext:
    """Returns a minimal context used when the backend is unreachable."""
    return PortfolioContext(
        username=username,
        name="the developer",
        title="Developer",
        about_me=(
            "Portfolio information could not be loaded. "
            "Let visitors know they can try again later or contact the developer directly."
        ),
        introduction="",
        skills=[],
        technologies=[],
        current_position=None,
        experience=[],
        education=[],
        projects=[],
        top_repositories=[],
        github_username=None,
        linkedin=None,
        personal_website=None,
        agent_name="Alex",
        agent_tone="balanced",
        agent_verbosity="concise",
        technical_depth="medium",
        voice_id=None,
    )


async def fetch_portfolio_context(username: str) -> PortfolioContext:
    backend_url = os.environ["BACKEND_URL"]
    url = f"{backend_url}/agent/context/{username}"
    logger.info("Fetching portfolio context from %s", url)

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
