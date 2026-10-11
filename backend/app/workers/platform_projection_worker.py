"""Consume canonical platform events from an SQS subscription."""

import argparse
import asyncio
import json
import logging

import boto3

from app.core.config import Settings, get_settings
from app.core.database import async_session_factory
from app.services.shared.platform_authorization import get_platform_authorization
from app.services.shared.platform_projection_service import PlatformEvent, apply_platform_event

logger = logging.getLogger(__name__)


async def consume_once(settings: Settings | None = None, *, max_messages: int = 10) -> int:
    resolved = settings or get_settings()
    if not resolved.platform_event_queue_url:
        raise ValueError("platform event queue URL is not configured")
    sqs = boto3.client(
        "sqs",
        region_name=resolved.platform_event_region,
        endpoint_url=resolved.platform_event_endpoint_url,
    )
    result = await asyncio.to_thread(
        sqs.receive_message,
        QueueUrl=resolved.platform_event_queue_url,
        MaxNumberOfMessages=min(max_messages, 10),
        WaitTimeSeconds=10,
    )
    consumed = 0
    for message in result.get("Messages", []):
        try:
            body = json.loads(message["Body"])
            event = PlatformEvent.parse(body.get("detail", body))
            async with async_session_factory() as session:
                await apply_platform_event(session, event)
                await session.commit()
        except Exception:
            logger.exception(
                "Platform projection deferred; message remains available for retry",
                extra={"message_id": message.get("MessageId")},
            )
            continue
        if event.type == "platform.membership.changed.v1":
            get_platform_authorization().invalidate(study_id=event.aggregate_id)
        elif event.type.startswith("platform.user."):
            get_platform_authorization().invalidate()
        await asyncio.to_thread(
            sqs.delete_message,
            QueueUrl=resolved.platform_event_queue_url,
            ReceiptHandle=message["ReceiptHandle"],
        )
        consumed += 1
    return consumed


async def run_forever(settings: Settings | None = None) -> None:
    """Continuously long-poll without acknowledging failed projections."""

    while True:
        try:
            await consume_once(settings)
        except Exception:
            logger.exception("Platform projection poll failed; retrying")
            await asyncio.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Continue long-polling for events")
    args = parser.parse_args()
    asyncio.run(run_forever() if args.watch else consume_once())
