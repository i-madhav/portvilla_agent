import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from livekit import rtc
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
from .assistant import IntroAssistant, PortvillaAssistant
from .ui_commands import emit_ui_command, UICommandType
from .prompts import INTRO_GREETING

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env.local")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("portvilla.main")

STT_MODEL = "deepgram/nova-3"
LLM_MODEL = "openai/gpt-4o-mini"
TTS_MODEL = "cartesia/sonic-2"
DEFAULT_TTS_VOICE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

server = AgentServer()

# ---------------------------------------------------------------------------
# Intro greeting cache
# ---------------------------------------------------------------------------
# The intro greeting is identical for every visitor, so we synthesize it once
# and reuse the audio frames for all subsequent sessions — eliminating TTS
# latency on the most critical moment of the experience.

_intro_tts = inference.TTS(model=TTS_MODEL, voice=DEFAULT_TTS_VOICE)
_intro_audio_frames: list[rtc.AudioFrame] = []
_intro_cache_lock = asyncio.Lock()


async def _get_intro_audio() -> list[rtc.AudioFrame]:
    """Synthesize INTRO_GREETING on first call; return cached frames on all subsequent calls."""
    global _intro_audio_frames
    async with _intro_cache_lock:
        if not _intro_audio_frames:
            logger.info("Pre-synthesizing intro greeting...")
            async for event in _intro_tts.synthesize(INTRO_GREETING):
                _intro_audio_frames.append(event.frame)
            logger.info("Intro greeting cached (%d frames)", len(_intro_audio_frames))
    return _intro_audio_frames


# ---------------------------------------------------------------------------
# Process setup
# ---------------------------------------------------------------------------


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


# ---------------------------------------------------------------------------
# Intro agent session
# ---------------------------------------------------------------------------


@server.rtc_session(agent_name="portvilla-intro")
async def intro_agent(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("Dispatched intro agent | room=%s", ctx.room.name)

    await ctx.connect()

    session = AgentSession[AppUserData](
        userdata=AppUserData(ctx=ctx, portfolio=None),
        stt=inference.STT(model=STT_MODEL, language="multi"),
        llm=inference.LLM(model=LLM_MODEL),
        tts=inference.TTS(model=TTS_MODEL, voice=DEFAULT_TTS_VOICE),
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel()),
    )

    @session.on("user_input_transcribed")
    def on_user_input(ev: UserInputTranscribedEvent) -> None:
        logger.info("STT transcribed | final=%s | text=%r", ev.is_final, ev.transcript)

    @session.on("metrics_collected")
    def on_metrics(ev: MetricsCollectedEvent) -> None:
        logger.info("METRICS | %s", ev.metrics)

    await session.start(room=ctx.room, agent=IntroAssistant())
    logger.info("Intro session started")

    # appears while the audio is still playing.
    intro_frames = await _get_intro_audio()

    async def _stream_intro_frames():
        for frame in intro_frames:
            yield frame

    # adding await for sequential execution to ensure the greeting is played before showing the waitlist input
    await session.say(INTRO_GREETING, audio=_stream_intro_frames() , allow_interruptions=False)
    await emit_ui_command(ctx.room, UICommandType.SHOW_WAITLIST)
    logger.info("Intro greeting playing, waitlist input shown")


if __name__ == "__main__":
    cli.run_app(server)