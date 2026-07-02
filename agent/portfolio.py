import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    TurnHandlingOptions,
    UserInputTranscribedEvent,
    cli,
    inference,
)
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .context import fetch_portfolio_context, fallback_portfolio_context, AppUserData
from .assistant import PortvillaAssistant

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env.local")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("portvilla.portfolio")

STT_MODEL = "deepgram/nova-3"
LLM_MODEL = "openai/gpt-4o-mini"
TTS_MODEL = "cartesia/sonic-2"
DEFAULT_TTS_VOICE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="portvilla-portfolio")
async def portfolio_agent(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("Dispatched portfolio agent | room=%s", ctx.room.name)

    await ctx.connect()

    # Resolve the portfolio owner's username from job metadata (preferred) or room name.
    username: str | None = None
    try:
        meta = json.loads(ctx.job.metadata or "{}")
        username = meta.get("username")
    except (json.JSONDecodeError, AttributeError):
        pass

    if not username:
        # Fallback: room name is expected to be "{username}-{suffix}" or just "{username}".
        username = ctx.room.name.split("-")[0]

    # Fetch portfolio data; fall back to a minimal context if the backend is unreachable.
    try:
        portfolio = await fetch_portfolio_context(username)
        logger.info("Portfolio context loaded for %s", portfolio.name)
    except Exception as exc:
        logger.warning(
            "Failed to fetch portfolio context for %r: %s — using fallback", username, exc
        )
        portfolio = fallback_portfolio_context(username)

    voice = portfolio.voice_id or DEFAULT_TTS_VOICE

    session = AgentSession[AppUserData](
        userdata=AppUserData(ctx=ctx, portfolio=portfolio),
        stt=inference.STT(model=STT_MODEL, language="multi"),
        llm=inference.LLM(model=LLM_MODEL),
        tts=inference.TTS(model=TTS_MODEL, voice=voice),
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel()),
    )

    @session.on("user_input_transcribed")
    def on_user_input(ev: UserInputTranscribedEvent) -> None:
        logger.info("STT transcribed | final=%s | text=%r", ev.is_final, ev.transcript)

    @session.on("metrics_collected")
    def on_metrics(ev: MetricsCollectedEvent) -> None:
        logger.info("METRICS | %s", ev.metrics)

    await session.start(room=ctx.room, agent=PortvillaAssistant(portfolio))
    logger.info("Portfolio session started for %s", portfolio.name)


if __name__ == "__main__":
    cli.run_app(server)
