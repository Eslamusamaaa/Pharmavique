"""Voice endpoints (B5 voice search, B16 listen): speech to text and the Saudi Arabic voice.

Audio is processed in memory and never stored or logged (CLAUDE.md: health data).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from pharmavique.voice.application.extract import ExtractDrugName
from pharmavique.voice.application.speak import MAX_AUDIO_BYTES, MAX_TEXT, Speak, Transcribe
from pharmavique.voice.infrastructure.audio_cache import AudioStore
from pharmavique.voice.infrastructure.groq_speech import SpeechError

router = APIRouter(prefix="/v1/voice", tags=["voice"])
NOT_CONFIGURED = "voice is not configured: set PHARMAVIQUE_GROQ_API_KEY"


class TranscriptOut(BaseModel):
    text: str


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    as_link: bool = False  # True: answer with a one-time link the app's audio player can open


class DrugNameIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)  # what the person said, as transcribed


class DrugNameOut(BaseModel):
    query: str  # what to search for: the drug name, not the whole sentence
    name: str | None  # the name the model found; None when the rules cleaned the text instead
    understood: bool


class SpokenLinkOut(BaseModel):
    url: str  # relative to the API: GET it once within 10 minutes
    media_type: str


def get_transcribe(request: Request) -> Transcribe:
    backend: Transcribe | None = request.app.state.transcribe
    if backend is None:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    return backend


def get_speak(request: Request) -> Speak:
    backend: Speak | None = request.app.state.speak
    if backend is None:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    return backend


@router.post("/transcribe", response_model=TranscriptOut, summary="Speech to text (Arabic)")
async def transcribe(
    audio: Annotated[UploadFile, File(description="the recorded question, up to 25 MB")],
    backend: Annotated[Transcribe, Depends(get_transcribe)],
    language: str = "ar",
) -> TranscriptOut:
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    try:
        text = await backend.run(data, audio.filename or "audio", language)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SpeechError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        del data  # never kept beyond the request
    return TranscriptOut(text=text)


@router.post(
    "/speak",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}, "audio/wav": {}}}},
    summary="Text to speech in the Saudi Arabic voice (MP3 or WAV, per provider)",
)
async def speak(
    body: SpeakIn, request: Request, backend: Annotated[Speak, Depends(get_speak)]
) -> Response:
    try:
        audio = await backend.run(body.text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SpeechError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if body.as_link:
        cache: AudioStore = request.app.state.audio_cache
        key = await cache.put(audio.content, audio.media_type)
        link = SpokenLinkOut(url=f"/v1/voice/audio/{key}", media_type=audio.media_type)
        return Response(content=link.model_dump_json(), media_type="application/json")
    return Response(content=audio.content, media_type=audio.media_type)


@router.get("/audio/{key}", summary="Fetch a spoken answer once by its short-lived link")
async def audio(key: str, request: Request) -> Response:
    cache: AudioStore = request.app.state.audio_cache
    found = await cache.take(key)
    if found is None:
        raise HTTPException(status_code=404, detail="this audio link has expired")
    content, media_type = found
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post(
    "/drug-name",
    response_model=DrugNameOut,
    summary="The drug name inside a spoken request, to search for",
)
async def drug_name(body: DrugNameIn, request: Request) -> DrugNameOut:
    extract: ExtractDrugName = request.app.state.extract_name
    try:
        spoken = await extract.run(body.text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return DrugNameOut(query=spoken.query, name=spoken.name, understood=spoken.understood)
