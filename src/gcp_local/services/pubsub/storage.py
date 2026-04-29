"""In-memory storage for the Pub/Sub emulator.

The storage layer owns CRUD on TopicRecord / SubscriptionRecord and the
append-only message lists per topic. Delivery state (cursors, leases,
NACK queue, ordering blocks) lives in ``engine/backlog.py`` keyed by
``(project, subscription_id)``; storage just hands out the raw lists.
"""

import asyncio
from typing import Protocol

from gcp_local.services.pubsub.errors import (
    SubscriptionAlreadyExists,
    SubscriptionNotFound,
    TopicAlreadyExists,
    TopicNotFound,
)
from gcp_local.services.pubsub.models import (
    MessageRecord,
    SubscriptionRecord,
    TopicRecord,
)


class PubSubStorage(Protocol):
    async def create_topic(self, topic: TopicRecord) -> None: ...
    async def get_topic(self, project: str, topic_id: str) -> TopicRecord: ...
    async def update_topic(self, topic: TopicRecord) -> None: ...
    async def delete_topic(self, project: str, topic_id: str) -> None: ...
    async def list_topics(self, project: str) -> list[TopicRecord]: ...
    async def list_topic_subscriptions(self, project: str, topic_id: str) -> list[str]: ...
    async def create_subscription(self, sub: SubscriptionRecord) -> None: ...
    async def get_subscription(self, project: str, subscription_id: str) -> SubscriptionRecord: ...
    async def update_subscription(self, sub: SubscriptionRecord) -> None: ...
    async def delete_subscription(self, project: str, subscription_id: str) -> None: ...
    async def list_subscriptions(self, project: str) -> list[SubscriptionRecord]: ...
    async def append_message(self, project: str, topic_id: str, msg: MessageRecord) -> int: ...
    async def get_messages(self, project: str, topic_id: str) -> list[MessageRecord]: ...
    async def reset(self) -> None: ...


class InMemoryStorage:
    """Thread/asyncio-safe in-memory implementation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._topics: dict[tuple[str, str], TopicRecord] = {}
        self._subs: dict[tuple[str, str], SubscriptionRecord] = {}
        self._messages: dict[tuple[str, str], list[MessageRecord]] = {}

    async def create_topic(self, topic: TopicRecord) -> None:
        async with self._lock:
            key = (topic.project, topic.topic_id)
            if key in self._topics:
                raise TopicAlreadyExists(f"projects/{topic.project}/topics/{topic.topic_id}")
            self._topics[key] = topic
            self._messages.setdefault(key, [])

    async def get_topic(self, project: str, topic_id: str) -> TopicRecord:
        async with self._lock:
            try:
                return self._topics[(project, topic_id)]
            except KeyError:
                raise TopicNotFound(f"projects/{project}/topics/{topic_id}") from None

    async def update_topic(self, topic: TopicRecord) -> None:
        async with self._lock:
            key = (topic.project, topic.topic_id)
            if key not in self._topics:
                raise TopicNotFound(f"projects/{topic.project}/topics/{topic.topic_id}")
            self._topics[key] = topic

    async def delete_topic(self, project: str, topic_id: str) -> None:
        async with self._lock:
            key = (project, topic_id)
            if key not in self._topics:
                raise TopicNotFound(f"projects/{project}/topics/{topic_id}")
            del self._topics[key]
            self._messages.pop(key, None)

    async def list_topics(self, project: str) -> list[TopicRecord]:
        async with self._lock:
            return [t for (p, _), t in self._topics.items() if p == project]

    async def list_topic_subscriptions(self, project: str, topic_id: str) -> list[str]:
        async with self._lock:
            return [
                f"projects/{s.project}/subscriptions/{s.subscription_id}"
                for s in self._subs.values()
                if s.topic_project == project and s.topic_id == topic_id
            ]

    async def create_subscription(self, sub: SubscriptionRecord) -> None:
        async with self._lock:
            tkey = (sub.topic_project, sub.topic_id)
            if tkey not in self._topics:
                raise TopicNotFound(f"projects/{sub.topic_project}/topics/{sub.topic_id}")
            skey = (sub.project, sub.subscription_id)
            if skey in self._subs:
                raise SubscriptionAlreadyExists(
                    f"projects/{sub.project}/subscriptions/{sub.subscription_id}"
                )
            self._subs[skey] = sub

    async def get_subscription(self, project: str, subscription_id: str) -> SubscriptionRecord:
        async with self._lock:
            try:
                return self._subs[(project, subscription_id)]
            except KeyError:
                raise SubscriptionNotFound(
                    f"projects/{project}/subscriptions/{subscription_id}"
                ) from None

    async def update_subscription(self, sub: SubscriptionRecord) -> None:
        async with self._lock:
            key = (sub.project, sub.subscription_id)
            if key not in self._subs:
                raise SubscriptionNotFound(
                    f"projects/{sub.project}/subscriptions/{sub.subscription_id}"
                )
            self._subs[key] = sub

    async def delete_subscription(self, project: str, subscription_id: str) -> None:
        async with self._lock:
            key = (project, subscription_id)
            if key not in self._subs:
                raise SubscriptionNotFound(f"projects/{project}/subscriptions/{subscription_id}")
            del self._subs[key]

    async def list_subscriptions(self, project: str) -> list[SubscriptionRecord]:
        async with self._lock:
            return [s for (p, _), s in self._subs.items() if p == project]

    async def append_message(self, project: str, topic_id: str, msg: MessageRecord) -> int:
        async with self._lock:
            key = (project, topic_id)
            if key not in self._topics:
                raise TopicNotFound(f"projects/{project}/topics/{topic_id}")
            lst = self._messages.setdefault(key, [])
            lst.append(msg)
            return len(lst) - 1

    async def get_messages(self, project: str, topic_id: str) -> list[MessageRecord]:
        async with self._lock:
            return list(self._messages.get((project, topic_id), []))

    async def reset(self) -> None:
        async with self._lock:
            self._topics.clear()
            self._subs.clear()
            self._messages.clear()
