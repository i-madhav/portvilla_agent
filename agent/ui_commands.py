import json
import logging
from dataclasses import dataclass
from enum import Enum
from livekit import rtc

logger = logging.getLogger("portvilla.ui_commands")

UI_COMMAND_TOPIC = "ui-command"


class UICommandType(str, Enum):
    ORB_FULLSCREEN = "ORB_FULLSCREEN"
    ORB_TO_PIP = "ORB_TO_PIP"
    SHOW_PROJECT = "SHOW_PROJECT"
    SHOW_TECH_STACK = "SHOW_TECH_STACK"
    SHOW_GITHUB = "SHOW_GITHUB"
    SHOW_EXPERIENCE = "SHOW_EXPERIENCE"
    CLEAR_CONTENT = "CLEAR_CONTENT"
    SHOW_WAITLIST = "SHOW_WAITLIST"


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


async def emit_ui_command(
    room: rtc.Room,
    command_type: UICommandType,
    payload: dict | None = None,
) -> None:
    message: dict = {"type": command_type.value}
    if payload:
        message["payload"] = payload
    data = json.dumps(message).encode("utf-8")
    logger.debug("Emitting UI command: %s", command_type.value)
    await room.local_participant.publish_data(
        data,
        reliable=True,
        topic=UI_COMMAND_TOPIC,
    )
