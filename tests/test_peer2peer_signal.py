"""Tests for hort.peer2peer.signal."""

from __future__ import annotations

import asyncio
import json

import pytest

from hort.peer2peer.models import NatType, PeerInfo
from hort.peer2peer.signal import CallbackSignaling, SignalingChannel


class TestCallbackSignaling:
    @pytest.mark.asyncio
    async def test_send_offer_calls_callback(self) -> None:
        sent: list[dict] = []

        async def on_send(data: dict) -> None:
            sent.append(data)

        channel = CallbackSignaling(on_send=on_send)
        peer = PeerInfo(
            peer_id="test", public_ip="1.2.3.4", public_port=5678,
            nat_type=NatType.PORT_RESTRICTED,
        )
        await channel.send_offer(peer)
        assert len(sent) == 1
        assert sent[0]["peer_id"] == "test"
        assert sent[0]["public_ip"] == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_wait_answer_from_dict(self) -> None:
        async def noop(data: dict) -> None:
            pass

        channel = CallbackSignaling(on_send=noop)
        # Deliver answer
        await channel.deliver({
            "peer_id": "remote",
            "public_ip": "5.6.7.8",
            "public_port": 9012,
        })
        peer = await channel.wait_answer(timeout=1.0)
        assert peer.peer_id == "remote"
        assert peer.public_ip == "5.6.7.8"
        assert peer.public_port == 9012

    @pytest.mark.asyncio
    async def test_wait_answer_from_json_string(self) -> None:
        async def noop(data: dict) -> None:
            pass

        channel = CallbackSignaling(on_send=noop)
        await channel.deliver(json.dumps({
            "peer_id": "json-peer",
            "public_ip": "10.0.0.1",
            "public_port": 1234,
        }))
        peer = await channel.wait_answer(timeout=1.0)
        assert peer.peer_id == "json-peer"

    @pytest.mark.asyncio
    async def test_wait_answer_timeout(self) -> None:
        async def noop(data: dict) -> None:
            pass

        channel = CallbackSignaling(on_send=noop)
        with pytest.raises(TimeoutError):
            await channel.wait_answer(timeout=0.05)

    @pytest.mark.asyncio
    async def test_exchange(self) -> None:
        sent: list[dict] = []

        async def on_send(data: dict) -> None:
            sent.append(data)

        channel = CallbackSignaling(on_send=on_send)

        # Simulate remote delivering their answer before exchange
        async def deliver_later() -> None:
            await asyncio.sleep(0.01)
            await channel.deliver({
                "peer_id": "remote",
                "public_ip": "5.6.7.8",
                "public_port": 9012,
            })

        asyncio.create_task(deliver_later())

        local = PeerInfo(peer_id="local", public_ip="1.2.3.4", public_port=5678)
        remote = await channel.exchange(local, timeout=2.0)

        assert len(sent) == 1
        assert remote.peer_id == "remote"

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        async def noop(data: dict) -> None:
            pass

        channel = CallbackSignaling(on_send=noop)
        await channel.close()  # should not raise
