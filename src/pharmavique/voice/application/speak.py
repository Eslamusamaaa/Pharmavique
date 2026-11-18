"""Use cases: speak a text in the Saudi Arabic voice, and transcribe a voice question."""

from dataclasses import dataclass

from pharmavique.voice.application.ports import SpeechToText, TextToSpeech
from pharmavique.voice.domain.speech import speakable, split_for_speech

MAX_TEXT = 4000  # a few spoken paragraphs; assistant answers are much shorter
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # the provider's free-tier upload limit


@dataclass(frozen=True, slots=True)
class SpokenAudio:
    content: bytes
    media_type: str  # for example "audio/mpeg" or "audio/wav"


class Speak:
    def __init__(self, tts: TextToSpeech) -> None:
        self._tts = tts

    async def run(self, text: str) -> SpokenAudio:
        clean = speakable(text)[:MAX_TEXT]
        if not clean:
            raise ValueError("nothing to say")
        segments = split_for_speech(clean, self._tts.max_segment)
        return SpokenAudio(await self._tts.synthesize(segments), self._tts.media_type)


class Transcribe:
    def __init__(self, stt: SpeechToText) -> None:
        self._stt = stt

    async def run(self, audio: bytes, filename: str, language: str = "ar") -> str:
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("audio must be between 1 byte and 25 MB")
        return (await self._stt.transcribe(audio, filename, language)).strip()
