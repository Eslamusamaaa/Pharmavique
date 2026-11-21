"""What the background workers do: read a photo, answer a question.

Each handler runs the same use case the synchronous endpoint runs and returns the same JSON the
endpoint would have returned, so the app shows a job's result exactly like a direct answer. Failures
become short codes (see `foundation.jobs`); no text from the photo or the question is ever kept in
the job state.
"""

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AssistantBusy
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.bootstrap.api_assistant import AskIn, answer_out
from pharmavique.bootstrap.api_recognition import scan_out
from pharmavique.foundation.jobs import JobFailure, JobHandler, JobInput
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.recognition.domain.scans import ScanKind
from pharmavique.recognition.infrastructure.openai_vision import VisionError

SCAN = "scan"
ASSISTANT = "assistant"


def scan_handler(scanner: ScanImage) -> JobHandler:
    async def handle(job: JobInput) -> Mapping[str, Any]:
        try:
            kind = ScanKind(job.meta.get("kind", ScanKind.BOX.value))
            result = await scanner.run(job.data, str(job.meta.get("content_type", "")), kind)
        except ValueError:
            raise JobFailure("invalid_image") from None
        except VisionError:
            raise JobFailure("vision_unavailable", 502) from None
        return scan_out(result).model_dump(mode="json")

    return handle


def assistant_handler(assistant: AskAssistant) -> JobHandler:
    async def handle(job: JobInput) -> Mapping[str, Any]:
        try:
            body = AskIn.model_validate(json.loads(job.data))
            answer = await assistant.ask(
                body.question,
                body.level,
                body.register_number,
                spoken=body.spoken,
                history=[Turn(t.role, t.text) for t in body.history],
            )
        except (ValueError, ValidationError):
            raise JobFailure("invalid_question") from None
        except AssistantBusy:
            raise JobFailure("busy", 429) from None
        return answer_out(answer).model_dump(mode="json")

    return handle


def build_handlers(
    scanner: ScanImage | None, assistant: AskAssistant | None
) -> dict[str, JobHandler]:
    """Only the features that are configured get a handler."""
    handlers: dict[str, JobHandler] = {}
    if scanner is not None:
        handlers[SCAN] = scan_handler(scanner)
    if assistant is not None:
        handlers[ASSISTANT] = assistant_handler(assistant)
    return handlers
