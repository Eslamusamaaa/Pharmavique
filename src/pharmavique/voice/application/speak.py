"""Use cases: speak a text in the Saudi Arabic voice, and transcribe a voice question.

Each takes a first provider and free backups, tried in order: any failure of one provider moves
the request to the next, and only when all fail is the last error raised.
"""

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
    def __init__(self, tts: TextToSpeech, *backups: TextToSpeech) -> None:
        self._voices = [tts, *backups]

    async def run(self, text: str) -> SpokenAudio:
        clean = speakable(text)[:MAX_TEXT]
        if not clean:
            raise ValueError("nothing to say")
        for position, voice in enumerate(self._voices):
            # each provider takes its own segment length, so the text is cut for each one
            segments = split_for_speech(clean, voice.max_segment)
            try:
                return SpokenAudio(await voice.synthesize(segments), voice.media_type)
            except Exception:  # any failure of this provider: the next one is asked
                if position == len(self._voices) - 1:
                    raise
        raise RuntimeError("no voice to ask")  # not reached: there is always one


class Transcribe:
    def __init__(self, stt: SpeechToText, *backups: SpeechToText) -> None:
        self._listeners = [stt, *backups]

    async def run(self, audio: bytes, filename: str, language: str = "ar") -> str:
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("audio must be between 1 byte and 25 MB")
        for position, listener in enumerate(self._listeners):
            try:
                return (await listener.transcribe(audio, filename, language)).strip()
            except Exception:  # any failure of this provider: the next one is asked
                if position == len(self._listeners) - 1:
                    raise
        raise RuntimeError("no listener to ask")  # not reached: there is always one
