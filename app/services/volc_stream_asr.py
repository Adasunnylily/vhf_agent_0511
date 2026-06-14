from __future__ import annotations

import asyncio
import gzip
import json
import os
import struct
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_SAMPLE_RATE = 16000


class ProtocolVersion:
    V1 = 0b0001


class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111


class MessageTypeSpecificFlags:
    POS_SEQUENCE = 0b0001
    NEG_WITH_SEQUENCE = 0b0011


class SerializationType:
    JSON = 0b0001


class CompressionType:
    GZIP = 0b0001


def gzip_compress(data: bytes) -> bytes:
    return gzip.compress(data)


def gzip_decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


def judge_wav(data: bytes) -> bool:
    return len(data) >= 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def read_wav_info(data: bytes) -> Tuple[int, int, int, int, bytes]:
    if len(data) < 44:
        raise ValueError("Invalid WAV file: too short")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Invalid WAV file")
    num_channels = struct.unpack("<H", data[22:24])[0]
    sample_rate = struct.unpack("<I", data[24:28])[0]
    bits_per_sample = struct.unpack("<H", data[34:36])[0]
    pos = 36
    while pos < len(data) - 8:
        subchunk_id = data[pos : pos + 4]
        subchunk_size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        if subchunk_id == b"data":
            wave_data = data[pos + 8 : pos + 8 + subchunk_size]
            frame_count = subchunk_size // max(1, num_channels * (bits_per_sample // 8))
            return num_channels, bits_per_sample // 8, sample_rate, frame_count, wave_data
        pos += 8 + subchunk_size
    raise ValueError("Invalid WAV file: no data subchunk found")


class AsrRequestHeader:
    def __init__(self) -> None:
        self.message_type = MessageType.CLIENT_FULL_REQUEST
        self.message_type_specific_flags = MessageTypeSpecificFlags.POS_SEQUENCE
        self.serialization_type = SerializationType.JSON
        self.compression_type = CompressionType.GZIP
        self.reserved_data = bytes([0x00])

    def with_message_type(self, message_type: int) -> "AsrRequestHeader":
        self.message_type = message_type
        return self

    def with_message_type_specific_flags(self, flags: int) -> "AsrRequestHeader":
        self.message_type_specific_flags = flags
        return self

    def to_bytes(self) -> bytes:
        header = bytearray()
        header.append((ProtocolVersion.V1 << 4) | 1)
        header.append((self.message_type << 4) | self.message_type_specific_flags)
        header.append((self.serialization_type << 4) | self.compression_type)
        header.extend(self.reserved_data)
        return bytes(header)


class AsrResponse:
    def __init__(self) -> None:
        self.code = 0
        self.is_last_package = False
        self.payload_msg: Optional[Dict[str, Any]] = None


def parse_response(msg: bytes) -> AsrResponse:
    response = AsrResponse()
    header_size = msg[0] & 0x0F
    message_type = msg[1] >> 4
    message_type_specific_flags = msg[1] & 0x0F
    serialization_method = msg[2] >> 4
    message_compression = msg[2] & 0x0F
    payload = msg[header_size * 4 :]

    if message_type_specific_flags & 0x01:
        payload = payload[4:]
    if message_type_specific_flags & 0x02:
        response.is_last_package = True
    if message_type_specific_flags & 0x04:
        payload = payload[4:]

    if message_type == MessageType.SERVER_FULL_RESPONSE:
        payload = payload[4:]
    elif message_type == MessageType.SERVER_ERROR_RESPONSE:
        response.code = struct.unpack(">i", payload[:4])[0]
        payload = payload[8:]

    if not payload:
        return response

    if message_compression == CompressionType.GZIP:
        payload = gzip_decompress(payload)

    if serialization_method == SerializationType.JSON:
        parsed = json.loads(payload.decode("utf-8"))
        if isinstance(parsed, dict):
            response.payload_msg = parsed
    return response


def build_auth_headers(
    *,
    app_key: str,
    access_key: str,
    api_key: str,
    resource_id: str,
    uid: str,
) -> Dict[str, str]:
    request_id = str(uuid.uuid4())
    if app_key and access_key:
        return {
            "X-Api-App-Key": app_key,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
    if api_key:
        return {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
    raise RuntimeError("缺少 VOLCENGINE_ASR_APP_KEY/VOLCENGINE_ASR_ACCESS_KEY 或 VOLCENGINE_ASR_API_KEY")


from app.services.asr_prompts import build_volc_request_options


def build_full_client_request(seq: int, uid: str) -> bytes:
    header = (
        AsrRequestHeader()
        .with_message_type(MessageType.CLIENT_FULL_REQUEST)
        .with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
    )
    payload = {
        "user": {"uid": uid},
        "audio": {
            "format": "pcm",
            "codec": "raw",
            "rate": DEFAULT_SAMPLE_RATE,
            "bits": 16,
            "channel": 1,
        },
        "request": build_volc_request_options(streaming=True),
    }
    compressed_payload = gzip_compress(json.dumps(payload).encode("utf-8"))
    request = bytearray()
    request.extend(header.to_bytes())
    request.extend(struct.pack(">i", seq))
    request.extend(struct.pack(">I", len(compressed_payload)))
    request.extend(compressed_payload)
    return bytes(request)


def build_audio_only_request(seq: int, segment: bytes, *, is_last: bool) -> bytes:
    header = AsrRequestHeader().with_message_type(MessageType.CLIENT_AUDIO_ONLY_REQUEST)
    packet_seq = seq
    if is_last:
        header.with_message_type_specific_flags(MessageTypeSpecificFlags.NEG_WITH_SEQUENCE)
        packet_seq = -seq
    else:
        header.with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
    compressed_segment = gzip_compress(segment)
    request = bytearray()
    request.extend(header.to_bytes())
    request.extend(struct.pack(">i", packet_seq))
    request.extend(struct.pack(">I", len(compressed_segment)))
    request.extend(compressed_segment)
    return bytes(request)


def extract_stream_text(payload_msg: Optional[Dict[str, Any]]) -> str:
    if not payload_msg:
        return ""
    result = payload_msg.get("result")
    if isinstance(result, dict):
        text = str(result.get("text") or "").strip()
        if text:
            return text
        utterances = result.get("utterances")
        if isinstance(utterances, list):
            return "".join(str(item.get("text") or "") for item in utterances if isinstance(item, dict))
    return str(payload_msg.get("text") or "").strip()


def collect_best_text(responses: List[AsrResponse]) -> str:
    best = ""
    for response in responses:
        if response.code != 0:
            raise RuntimeError(f"火山流式ASR错误 code={response.code} payload={response.payload_msg}")
        text = extract_stream_text(response.payload_msg)
        if len(text) >= len(best):
            best = text
    return best


def split_audio(data: bytes, segment_size: int) -> List[bytes]:
    if segment_size <= 0:
        return [data]
    return [data[index : index + segment_size] for index in range(0, len(data), segment_size)]


class VolcStreamAsrClient:
    def __init__(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        uid: str,
        segment_duration_ms: int = 200,
    ) -> None:
        self.url = url
        self.headers = headers
        self.uid = uid
        self.segment_duration_ms = segment_duration_ms
        self.seq = 1
        self.conn: Any = None
        self.session: Any = None

    async def __aenter__(self) -> "VolcStreamAsrClient":
        try:
            import aiohttp
        except ImportError as exc:
            raise RuntimeError("缺少 aiohttp，请先安装: pip install aiohttp") from exc
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.conn and not self.conn.closed:
            await self.conn.close()
        if self.session and not self.session.closed:
            await self.session.close()

    async def transcribe_file(self, file_path: Path) -> str:
        content = file_path.read_bytes()
        if not judge_wav(content):
            raise RuntimeError(f"火山流式ASR需要 16k mono wav，当前文件: {file_path.name}")
        channel_num, samp_width, frame_rate, _, wave_data = read_wav_info(content)
        size_per_sec = channel_num * samp_width * frame_rate
        segment_size = max(1, size_per_sec * self.segment_duration_ms // 1000)

        import aiohttp

        self.conn = await self.session.ws_connect(self.url, headers=self.headers)
        await self.conn.send_bytes(build_full_client_request(self.seq, self.uid))
        self.seq += 1
        first_msg = await self.conn.receive()
        if first_msg.type != aiohttp.WSMsgType.BINARY:
            raise RuntimeError(f"火山流式ASR握手失败: {first_msg.type}")

        responses: List[AsrResponse] = [parse_response(first_msg.data)]
        segments = split_audio(wave_data, segment_size)

        async def sender() -> None:
            for index, segment in enumerate(segments):
                is_last = index == len(segments) - 1
                await self.conn.send_bytes(
                    build_audio_only_request(self.seq, segment, is_last=is_last)
                )
                if not is_last:
                    self.seq += 1
                await asyncio.sleep(self.segment_duration_ms / 1000)

        sender_task = asyncio.create_task(sender())
        try:
            async for msg in self.conn:
                if msg.type != aiohttp.WSMsgType.BINARY:
                    continue
                response = parse_response(msg.data)
                responses.append(response)
                if response.is_last_package or response.code != 0:
                    break
        finally:
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass

        text = collect_best_text(responses)
        if not text:
            raise RuntimeError(f"火山流式ASR未返回文本，responses={len(responses)}")
        return text


def transcribe_volc_stream_file(
    audio_path: Path,
    *,
    url: str,
    resource_id: str,
    segment_duration_ms: int = 200,
) -> str:
    app_key = os.getenv("VOLCENGINE_ASR_APP_KEY", "")
    access_key = os.getenv("VOLCENGINE_ASR_ACCESS_KEY", "")
    api_key = os.getenv("VOLCENGINE_ASR_API_KEY", "")
    uid = app_key or os.getenv("VOLCENGINE_ASR_UID", "vhf_agent_0511")
    headers = build_auth_headers(
        app_key=app_key,
        access_key=access_key,
        api_key=api_key,
        resource_id=resource_id,
        uid=uid,
    )

    async def _run() -> str:
        async with VolcStreamAsrClient(
            url=url,
            headers=headers,
            uid=uid,
            segment_duration_ms=segment_duration_ms,
        ) as client:
            return await client.transcribe_file(audio_path)

    return asyncio.run(_run())
