import hashlib

from pydantic import BaseModel, ConfigDict


class TarotModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
