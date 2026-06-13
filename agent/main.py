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
logger = logging.getLogger("portvilla")

STT_MODEL = "deepgram/nova-3"
LLM_MODEL = "openai/gpt-4o-mini"
TTS_MODEL = "cartesia/sonic-2"
DEFAULT_TTS_VOICE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm



@server.rtc_session(agent_name="portvilla-intro")
async def portvilla_agent(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    username = ctx.room.name.removeprefix("portvilla-")
    logger.info("Dispatched portvilla agent | room=%s | portfolio=%s", ctx.room.name, username)

    await ctx.connect()

    is_fallback = False
    try:
        portfolio = await fetch_portfolio_context(username)
    except Exception as exc:
        logger.error("Failed to fetch portfolio context: %s", exc)
        portfolio = fallback_portfolio_context(username)
        is_fallback = True

    session = AgentSession[AppUserData](
        userdata=AppUserData(ctx=ctx, portfolio=portfolio),
        stt=inference.STT(model=STT_MODEL, language="multi"),
        llm=inference.LLM(model=LLM_MODEL),
        tts=inference.TTS(model=TTS_MODEL, voice=portfolio.voice_id or DEFAULT_TTS_VOICE),
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel()),
    )

    @session.on("user_input_transcribed")
    def on_user_input(ev: UserInputTranscribedEvent) -> None:
        logger.info("STT transcribed | final=%s | text=%r", ev.is_final, ev.transcript)

    @session.on("metrics_collected")
    def on_metrics(ev: MetricsCollectedEvent) -> None:
        logger.info("METRICS | %s", ev.metrics)

    await session.start(
        room=ctx.room,
        agent=PortvillaAssistant(portfolio=portfolio),
    )
    logger.info("Session started, sending greeting")

    if is_fallback:
        greeting = (
            "Hi there! I'm Alex, a portfolio assistant. "
            "I wasn't able to load the full portfolio details right now — "
            "the backend may be offline. Feel free to ask me anything, "
            "but I may have limited information available."
        )
    else:
        greeting = (
            f"Hi! I'm {portfolio.agent_name}, here to tell you about "
            f"{portfolio.name}'s work and experience. What would you like to know?"
        )
    try:
        await session.generate_reply(instructions=greeting)
        logger.info("Greeting sent")
    except Exception as exc:
        logger.error("Failed to send greeting: %s", exc)


if __name__ == "__main__":
    cli.run_app(server)
