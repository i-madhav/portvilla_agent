import dataclasses
import logging
from livekit.agents import Agent
from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext
from .ui_commands import (
    emit_ui_command,
    UICommandType,
    ShowProjectPayload,
    ShowTechStackPayload,
    ShowGithubPayload,
    ShowExperiencePayload,
)
from .context import PortfolioContext, AppUserData
from .prompts import build_system_prompt, INTRO_PROMPT

logger = logging.getLogger("portvilla.assistant")


class IntroAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INTRO_PROMPT)


class PortvillaAssistant(Agent):
    def __init__(self, portfolio: PortfolioContext) -> None:
        super().__init__(
            instructions=build_system_prompt(portfolio),
        )
        self._portfolio = portfolio

    @function_tool
    async def show_project(
        self, context: RunContext[AppUserData], project_name: str
    ) -> str:
        """Show a project card in the UI. Call this whenever you are about to describe
        a specific project. The card appears before you start speaking about it.

        Args:
            project_name: The name of the project to display.
        """
        room = context.userdata.ctx.room
        project = next(
            (p for p in self._portfolio.projects if p.name.lower() == project_name.lower()),
            None,
        )
        if not project:
            project = next(
                (p for p in self._portfolio.projects if project_name.lower() in p.name.lower()),
                None,
            )

        if project:
            await emit_ui_command(room, UICommandType.ORB_TO_PIP)
            await emit_ui_command(
                room,
                UICommandType.SHOW_PROJECT,
                dataclasses.asdict(
                    ShowProjectPayload(
                        name=project.name,
                        description=project.description,
                        url=project.url,
                        tech_stack=project.technologies,
                    )
                ),
            )
            logger.info("Showing project: %s", project.name)
            return f"Showing project: {project.name}."

        logger.warning("Project not found: %s", project_name)
        return f"No project found with name: {project_name}."

    @function_tool
    async def show_tech_stack(self, context: RunContext[AppUserData]) -> str:
        """Show the skills and tech stack grid. Call this when the visitor asks
        about technical skills, technologies, or what the developer knows.
        """
        room = context.userdata.ctx.room
        techs = [{"name": t, "category": "skill"} for t in self._portfolio.technologies]
        await emit_ui_command(room, UICommandType.ORB_TO_PIP)
        await emit_ui_command(
            room,
            UICommandType.SHOW_TECH_STACK,
            dataclasses.asdict(ShowTechStackPayload(technologies=techs)),
        )
        logger.info("Showing tech stack (%d technologies)", len(techs))
        return "Showing tech stack."

    @function_tool
    async def show_github(self, context: RunContext[AppUserData]) -> str:
        """Show GitHub stats and top repositories. Call this when the visitor asks
        about open source work, GitHub activity, or wants to browse code.
        """
        if not self._portfolio.github_username:
            return "No GitHub profile linked."

        room = context.userdata.ctx.room
        languages = list(
            {r.language for r in self._portfolio.top_repositories if r.language}
        )
        await emit_ui_command(room, UICommandType.ORB_TO_PIP)
        await emit_ui_command(
            room,
            UICommandType.SHOW_GITHUB,
            dataclasses.asdict(
                ShowGithubPayload(
                    username=self._portfolio.github_username,
                    top_repos=[r.name for r in self._portfolio.top_repositories[:5]],
                    languages=languages,
                )
            ),
        )
        logger.info("Showing GitHub profile for %s", self._portfolio.github_username)
        return "Showing GitHub profile."

    @function_tool
    async def show_experience(
        self, context: RunContext[AppUserData], company: str
    ) -> str:
        """Show a work experience card. Call this when discussing a specific role or company.

        Args:
            company: The company name to display experience for.
        """
        room = context.userdata.ctx.room
        exp = next(
            (
                e
                for e in self._portfolio.experience
                if company.lower() in e.get("company", "").lower()
            ),
            None,
        )

        if exp:
            await emit_ui_command(room, UICommandType.ORB_TO_PIP)
            await emit_ui_command(
                room,
                UICommandType.SHOW_EXPERIENCE,
                dataclasses.asdict(
                    ShowExperiencePayload(
                        company=exp["company"],
                        role=exp["title"],
                        period=f"{exp['startDate']} – {exp.get('endDate', 'Present')}",
                        description=exp.get("description", ""),
                    )
                ),
            )
            logger.info("Showing experience at %s", exp["company"])
            return f"Showing experience at {exp['company']}."

        logger.warning("Experience not found for company: %s", company)
        return f"No experience found for company: {company}."

    @function_tool
    async def return_to_orb(self, context: RunContext[AppUserData]) -> str:
        """Return the orb to fullscreen and clear displayed content.
        Call this when the conversation moves to a general topic with nothing specific to show.
        """
        room = context.userdata.ctx.room
        await emit_ui_command(room, UICommandType.CLEAR_CONTENT)
        await emit_ui_command(room, UICommandType.ORB_FULLSCREEN)
        logger.info("Returning to fullscreen orb")
        return "Returning to orb."
