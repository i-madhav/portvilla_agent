LiveKit docs › Multimodality › Speech & audio › Audio customization

---

# Audio customization

> Cache TTS responses, customize pronunciation, and adjust speech volume.

## Overview

LiveKit Agents provides several ways to customize how your agent sounds. You can adjust pronunciation of specific words, control speech volume, and cache TTS responses for fixed phrases to avoid redundant TTS calls and reduce latency.

## Caching TTS responses

For fixed phrases like greetings, hold messages, and error prompts, you can avoid TTS calls and save tokens by providing pre-synthesized audio to `session.say(text, audio=...)`. Playback uses your audio, and the text is still used for the transcript and chat context.

There are three approaches:

- [Pre-synthesized or prerecorded](#caching-tts-prerecorded) — Use audio you already have (files or one-time synthesis at startup). Best when the set of phrases is known and stable.
- [Automatic caching (reuse by key)](#caching-tts-automatic) — Synthesize on first use and cache frames by text. Reuse the same audio whenever that text is spoken again. Best when the agent might repeat the same phrases during a session or across sessions.
- [Using cached TTS in a tool call](#cached-tts-in-tools) — Play a pre-synthesized hold message while a tool executes, and cancel it early if the API returns quickly.

### Using pre-synthesized or prerecorded audio

Prerecord phrases as audio files or synthesize once at startup, load the audio into frames, and pass the frames to `say()` as the `audio` argument.

**Python**:

```python
from livekit.agents.utils.audio import audio_frames_from_file

await session.say(
    "Your phrase",
    audio=audio_frames_from_file(path, sample_rate=24000, num_channels=1),
)

```

---

**Node.js**:

```typescript
import { audioFramesFromFile } from '@livekit/agents';

await session.say('Your phrase', {
  audio: audioFramesFromFile(path, { sampleRate: 24000, numChannels: 1 }),
});

```

- **[Playing Audio](https://docs.livekit.io/reference/recipes/playing_audio.md)**: Full example of loading a WAV and streaming it via `say()` with the `audio` parameter, the same pattern used above for cached TTS.

### Automatic caching (reuse by key)

To reuse TTS output whenever the same text is spoken, synthesize on first use and cache the frames keyed by text. Use the same TTS instance you pass to `AgentSession`. On a cache hit, pass the cached frames to `say(text, audio=...)`, and on a cache miss, call `tts.synthesize(text)`, collect the frames, store them, then pass to `say()`.

To cache TTS for pipeline output (LLM-generated speech) as well, you can implement the same cache-and-reuse logic inside a [custom TTS node](https://docs.livekit.io/agents/build/nodes.md#tts_node). Be aware that cache lookup might require the full text segment, which can increase time-to-first-byte.

**Python**:

```python
from livekit import rtc
from livekit.agents import AgentSession

# Hold a reference to the TTS instance you pass to AgentSession.
tts_cache: dict[str, list[rtc.AudioFrame]] = {}

async def say_cached(session: AgentSession, tts, text: str) -> None:
    if text not in tts_cache:
        stream = tts.synthesize(text)
        frames: list[rtc.AudioFrame] = []
        async for event in stream:
            frames.append(event.frame)
        tts_cache[text] = frames

    async def audio_gen():
        for frame in tts_cache[text]:
            yield frame

    await session.say(text, audio=audio_gen())

```

---

**Node.js**:

```typescript
import { voice } from '@livekit/agents';
import type { AudioFrame } from '@livekit/rtc-node';

// Hold a reference to the TTS instance you pass to AgentSession.
const ttsCache = new Map<string, AudioFrame[]>();

async function sayCached(
  session: voice.AgentSession,
  tts: { synthesize(text: string): AsyncIterableIterator<{ frame: AudioFrame }> },
  text: string,
): Promise<void> {
  let frames = ttsCache.get(text);
  if (!frames) {
    frames = [];
    for await (const event of tts.synthesize(text)) {
      frames.push(event.frame);
    }
    ttsCache.set(text, frames);
  }

  const stream = new ReadableStream<AudioFrame>({
    start(controller) {
      for (const frame of frames!) {
        controller.enqueue(frame);
      }
      controller.close();
    },
  });
  await session.say(text, { audio: stream });
}

```

### Using cached TTS in a tool call

A common use case for cached TTS is playing a hold message like "let me check that for you" at the start of a [function tool](https://docs.livekit.io/agents/logic/tools.md) while waiting for an external API. Pre-synthesize the audio once at startup, then play it with `say()` inside the tool. If the API returns before the message finishes, interrupt the speech handle so the agent can immediately speak the result.

> ℹ️ **Note**
> 
> Don't `await` the `say()` call inside the tool. Awaiting waits for the speech to finish playing before continuing, which blocks the API call. Instead, capture the returned `SpeechHandle` and let the hold message play concurrently with your API request.

**Python**:

```python
from livekit import rtc
from livekit.agents import Agent, RunContext, function_tool

# Pre-synthesize a hold message once at startup
HOLD_FRAMES: list[rtc.AudioFrame] = []

async def preload_hold_message(tts) -> None:
    global HOLD_FRAMES
    async for event in tts.synthesize("Let me check that for you."):
        HOLD_FRAMES.append(event.frame)

class MyAgent(Agent):
    @function_tool()
    async def check_order_status(
        self,
        context: RunContext,
        order_id: str,
    ) -> str:
        """Check the status of an order.

        Args:
            order_id: The order ID to look up.
        """
        async def cached_audio():
            for frame in HOLD_FRAMES:
                yield frame

        # Play the hold message concurrently — don't await
        hold_handle = context.session.say(
            "Let me check that for you.",
            audio=cached_audio(),
            add_to_chat_ctx=False,
        )

        # Call the external API (runs while the hold message plays)
        result = await fetch_order_status(order_id)

        # If the API returned before the hold message finished, cancel it
        if not hold_handle.interrupted and not hold_handle.done():
            hold_handle.interrupt()

        return result

```

---

**Node.js**:

```typescript
import { voice, llm } from '@livekit/agents';
import type { AudioFrame } from '@livekit/rtc-node';
import { z } from 'zod';

// Pre-synthesize a hold message once at startup
let holdFrames: AudioFrame[] = [];

async function preloadHoldMessage(
  tts: { synthesize(text: string): AsyncIterableIterator<{ frame: AudioFrame }> },
) {
  holdFrames = [];
  for await (const event of tts.synthesize('Let me check that for you.')) {
    holdFrames.push(event.frame);
  }
}

class MyAgent extends voice.Agent {
  constructor() {
    super({
      instructions: 'You are a helpful assistant.',
      tools: {
        checkOrderStatus: llm.tool({
          description: 'Check the status of an order.',
          parameters: z.object({
            orderId: z.string().describe('The order ID to look up.'),
          }),
          execute: async ({ orderId }, { ctx }) => {
            // Play the hold message concurrently — don't await
            const stream = new ReadableStream<AudioFrame>({
              start(controller) {
                for (const frame of holdFrames) {
                  controller.enqueue(frame);
                }
                controller.close();
              },
            });
            const holdHandle = ctx.session.say('Let me check that for you.', {
              audio: stream,
              addToChatCtx: false,
            });

            // Call the external API (runs while the hold message plays)
            const result = await fetchOrderStatus(orderId);

            // If the API returned before the hold message finished, cancel it
            if (!holdHandle.interrupted && !holdHandle.done()) {
              holdHandle.interrupt();
            }

            return result;
          },
        }),
      },
    });
  }
}

```

> 💡 **Tip**
> 
> If the user speaks during the hold message, the tool is interrupted by default, the hold message stops, and the tool result is discarded. To ensure the tool always runs to completion (for example, if it performs a write operation), call `context.disallow_interruptions()` at the start of the tool.

## Customizing pronunciation

You can customize how your agent pronounces specific words using a built-in pronunciation map or a custom [tts_node](https://docs.livekit.io/agents/build/nodes.md#tts_node) override. Many TTS providers also support SSML tags for finer control — see the [SSML reference](#ssml-tags) below. Some providers offer their own pronunciation options — see [Google Gemini TTS](https://docs.livekit.io/agents/models/tts/gemini.md) and [Sarvam TTS](https://docs.livekit.io/agents/models/tts/sarvam.md) for examples.

### Using a pronunciation map

The simplest way to customize pronunciation is with a built-in map of terms to their replacement text. The agent applies the substitutions as a streaming text transform before TTS synthesis, handling terms that span across token boundaries without requiring a custom node override.

Use the [`text_transforms.replace()`](https://docs.livekit.io/agents/multimodality/text.md#built-in-replace-transform) function on `AgentSession` to define pronunciation replacements:

**Python**:

```python
from livekit.agents import AgentSession, text_transforms

session = AgentSession(
    # ... stt, llm, tts, etc.
    tts_text_transforms=[
        "filter_emoji",
        "filter_markdown",
        text_transforms.replace({
            "LiveKit": "Live Kit",
            "API": "A P I",
            "SQL": "sequel",
            "kubectl": "kube control",
            "nginx": "engine x",
        }),
    ],
)

```

---

**Node.js**:

```typescript
import { voice } from '@livekit/agents';

const session = new voice.AgentSession({
  // ... stt, llm, tts, etc.
  ttsTextTransforms: [
    'filter_emoji',
    'filter_markdown',
    voice.textTransforms.replace({
      'LiveKit': 'Live Kit',
      'API': 'A P I',
      'SQL': 'sequel',
      'kubectl': 'kube control',
      'nginx': 'engine x',
    }),
  ],
});

```

### Using a custom TTS node

For pronunciation logic beyond simple text replacement — such as regex-based matching, conditional rules, or context-dependent substitutions — use a custom [tts_node](https://docs.livekit.io/agents/build/nodes.md#tts_node) override:

** Filename: `agent.py`**

```python
async def tts_node(
    self,
    text: AsyncIterable[str],
    model_settings: ModelSettings
) -> AsyncIterable[rtc.AudioFrame]:
    # Pronunciation replacements for common technical terms and abbreviations.
    # Support for custom pronunciations depends on the TTS provider.
    pronunciations = {
        "API": "A P I",
        "REST": "rest",
        "SQL": "sequel",
        "kubectl": "kube control",
        "AWS": "A W S",
        "UI": "U I",
        "URL": "U R L",
        "npm": "N P M",
        "LiveKit": "Live Kit",
        "async": "a sink",
        "nginx": "engine x",
    }

    async def adjust_pronunciation(input_text: AsyncIterable[str]) -> AsyncIterable[str]:
        async for chunk in input_text:
            modified_chunk = chunk

            # Apply pronunciation rules
            for term, pronunciation in pronunciations.items():
                # Use word boundaries to avoid partial replacements
                modified_chunk = re.sub(
                    rf'\b{term}\b',
                    pronunciation,
                    modified_chunk,
                    flags=re.IGNORECASE
                )

            yield modified_chunk

    # Process with modified text through base TTS implementation
    async for frame in Agent.default.tts_node(
        self,
        adjust_pronunciation(text),
        model_settings
    ):
        yield frame

```

** Filename: `Required imports`**

```python
import re
from livekit import rtc
from livekit.agents.voice import ModelSettings
from livekit.agents import tts
from typing import AsyncIterable

```

** Filename: `agent.ts`**

```typescript
async ttsNode(
  text: ReadableStream<string>,
  modelSettings: voice.ModelSettings,
): Promise<ReadableStream<AudioFrame> | null> {
  // Pronunciation replacements for common technical terms and abbreviations.
  // Support for custom pronunciations depends on the TTS provider.
  const pronunciations = {
    API: 'A P I',
    REST: 'rest',
    SQL: 'sequel',
    kubectl: 'kube control',
    AWS: 'A W S',
    UI: 'U I',
    URL: 'U R L',
    npm: 'N P M',
    LiveKit: 'Live Kit',
    async: 'a sink',
    nginx: 'engine x',
  };

  const adjustPronunciation = (inputText: ReadableStream<string>): ReadableStream<string> => {
    return new ReadableStream({
      async start(controller) {
        const reader = inputText.getReader();
        try {
          while (true) {
            const { done, value: chunk } = await reader.read();
            if (done) break;

            let modifiedChunk = chunk;

            // Apply pronunciation rules
            for (const [term, pronunciation] of Object.entries(pronunciations)) {
              // Use word boundaries to avoid partial replacements
              const regex = new RegExp(`\\b${term}\\b`, 'gi');
              modifiedChunk = modifiedChunk.replace(regex, pronunciation);
            }

            controller.enqueue(modifiedChunk);
          }
        } finally {
          reader.releaseLock();
          controller.close();
        }
      },
    });
  };

  // Process with modified text through base TTS implementation
  return voice.Agent.default.ttsNode(this, adjustPronunciation(text), modelSettings);
}

```

** Filename: `Required imports`**

```typescript
import type { AudioFrame } from '@livekit/rtc-node';
import { ReadableStream } from 'stream/web';
import { voice } from '@livekit/agents';

```

### SSML tags

Many TTS providers support Speech Synthesis Markup Language (SSML) tags for finer control over pronunciation. SSML support varies by provider — see your provider's page (for example, [ElevenLabs](https://docs.livekit.io/agents/models/tts/elevenlabs.md), [Cartesia](https://docs.livekit.io/agents/models/tts/cartesia.md), [Google](https://docs.livekit.io/agents/models/tts/google.md)) for details. The following table lists commonly supported SSML tags:

| SSML Tag | Description |
| `phoneme` | Specify phonetic pronunciation using IPA or X-SAMPA notation. |
| `say-as` | Specifies how to interpret the enclosed text. For example, use `character` to speak each character individually, or `date` to specify a calendar date. |
| `lexicon` | A custom dictionary that defines the pronunciation of certain words using phonetic notation or text-to-pronunciation mappings. |
| `emphasis` | Speak text with an emphasis. |
| `break` | Add a manual pause. |
| `prosody` | Controls pitch, speaking rate, and volume of speech output. |

## Adjusting speech volume

To adjust the volume of the agent's speech, add a processor to the `tts_node` or the `realtime_audio_output_node`.  Alternatively, you can also [adjust the volume of playback](https://docs.livekit.io/transport/media/subscribe.md#volume) in the frontend SDK.

The following example agent has an adjustable volume between 0 and 100, and offers a [tool call](https://docs.livekit.io/agents/build/tools.md) to change it.

** Filename: `agent.py`**

```python
class Assistant(Agent):
    def __init__(self) -> None:
        self.volume: int = 50
        super().__init__(
            instructions=f"You are a helpful voice AI assistant. Your starting volume level is {self.volume}."
        )

    @function_tool()
    async def set_volume(self, volume: int):
        """Set the volume of the audio output.

        Args:
            volume (int): The volume level to set. Must be between 0 and 100.
        """
        self.volume = volume

    # Audio node used by STT-LLM-TTS pipeline models
    async def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
        return self._adjust_volume_in_stream(
            Agent.default.tts_node(self, text, model_settings)
        )

    # Audio node used by realtime models
    async def realtime_audio_output_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
    ) -> AsyncIterable[rtc.AudioFrame]:
        return self._adjust_volume_in_stream(
            Agent.default.realtime_audio_output_node(self, audio, model_settings)
        )

    async def _adjust_volume_in_stream(
        self, audio: AsyncIterable[rtc.AudioFrame]
    ) -> AsyncIterable[rtc.AudioFrame]:
        stream: utils.audio.AudioByteStream | None = None
        async for frame in audio:
            if stream is None:
                stream = utils.audio.AudioByteStream(
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                    samples_per_channel=frame.sample_rate // 10,  # 100ms
                )
            for f in stream.push(frame.data):
                yield self._adjust_volume_in_frame(f)

        if stream is not None:
            for f in stream.flush():
                yield self._adjust_volume_in_frame(f)

    def _adjust_volume_in_frame(self, frame: rtc.AudioFrame) -> rtc.AudioFrame:
        audio_data = np.frombuffer(frame.data, dtype=np.int16)
        audio_float = audio_data.astype(np.float32) / np.iinfo(np.int16).max
        audio_float = audio_float * max(0, min(self.volume, 100)) / 100.0
        processed = (audio_float * np.iinfo(np.int16).max).astype(np.int16)

        return rtc.AudioFrame(
            data=processed.tobytes(),
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            samples_per_channel=len(processed) // frame.num_channels,
        )

```

** Filename: `Required imports`**

```python
import numpy as np
from typing import AsyncIterable
from livekit.agents import Agent, function_tool, utils
from livekit import rtc

```

** Filename: `agent.ts`**

```typescript
class Assistant extends voice.Agent {
  private volume = 50;

  constructor(initialVolume: number) {
    super({
      instructions: `You are a helpful voice AI assistant. Your starting volume level is ${initialVolume}.`,
      tools: {
        setVolume: llm.tool({
          description: 'Set the volume of the audio output.',
          parameters: z.object({
            volume: z
              .number()
              .min(0)
              .max(100)
              .describe('The volume level to set. Must be between 0 and 100.'),
          }),
          execute: async ({ volume }) => {
            this.volume = volume;
            return `Volume set to ${volume}`;
          },
        }),
      },
    });
    this.volume = initialVolume;
  }

  // Audio node used by STT-LLM-TTS pipeline models
  async ttsNode(
    text: ReadableStream<string>,
    modelSettings: voice.ModelSettings,
  ): Promise<ReadableStream<AudioFrame> | null> {
    const baseStream = await voice.Agent.default.ttsNode(this, text, modelSettings);
    if (!baseStream) return null;
    return this.adjustVolumeInStream(baseStream);
  }

  // Audio node used by realtime models
  async realtimeAudioOutputNode(
    audio: ReadableStream<AudioFrame>,
    modelSettings: voice.ModelSettings,
  ): Promise<ReadableStream<AudioFrame> | null> {
    const baseStream = await voice.Agent.default.realtimeAudioOutputNode(
      this,
      audio,
      modelSettings,
    );
    if (!baseStream) return null;
    return this.adjustVolumeInStream(baseStream);
  }

  private adjustVolumeInStream(
    audioStream: ReadableStream<AudioFrame>,
  ): ReadableStream<AudioFrame> {
    return new ReadableStream({
      start: async (controller) => {
        const reader = audioStream.getReader();
        try {
          while (true) {
            const { done, value: frame } = await reader.read();
            if (done) break;

            const adjustedFrame = this.adjustVolumeInFrame(frame);
            controller.enqueue(adjustedFrame);
          }
        } finally {
          reader.releaseLock();
          controller.close();
        }
      },
    });
  }

  private adjustVolumeInFrame(frame: AudioFrame): AudioFrame {
    const audioData = new Int16Array(frame.data);
    const volumeMultiplier = Math.max(0, Math.min(this.volume, 100)) / 100.0;

    const processedData = new Int16Array(audioData.length);
    for (let i = 0; i < audioData.length; i++) {
      const floatSample = audioData[i]! / 32767.0;
      const adjustedSample = floatSample * volumeMultiplier;
      processedData[i] = Math.round(adjustedSample * 32767.0);
    }

    return new AudioFrame(processedData, frame.sampleRate, frame.channels, frame.samplesPerChannel);
  }
}

```

** Filename: `Required imports`**

```typescript
import { voice } from '@livekit/agents';
import { AudioFrame } from '@livekit/rtc-node';
import { ReadableStream } from 'stream/web';

```

## Additional resources

- **[Speech & audio overview](https://docs.livekit.io/agents/multimodality/audio.md)**: Control agent speech, handle interruptions, and initiate speech.

- **[Text-to-speech (TTS)](https://docs.livekit.io/agents/models/tts.md)**: TTS models for pipeline agents.

- **[Pipeline nodes & hooks](https://docs.livekit.io/agents/logic/nodes.md)**: Customize agent behavior with pipeline nodes.

---

This document was rendered at 2026-06-17T10:25:43.426Z.
For the latest version of this document, see [https://docs.livekit.io/agents/multimodality/audio/customization.md](https://docs.livekit.io/agents/multimodality/audio/customization.md).

To explore all LiveKit documentation, see [llms.txt](https://docs.livekit.io/llms.txt).