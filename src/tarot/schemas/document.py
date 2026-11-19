from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from tarot.schemas.base import TarotModel


class DocumentSource(StrEnum):
    EDGAR = "edgar"
    NVCA = "nvca"
    SERIES_SEED = "series_seed"
    YC_SAFE = "yc_safe"
    SYNTHETIC = "synthetic"
    UPLOAD = "upload"


class FileType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    HTML = "html"
    TXT = "txt"


class EdgarMetadata(TarotModel):
    cik: str = Field(pattern=r"^\d{10}$")
    accession_number: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    company_name: str
    form_type: str
    filing_date: date
    exhibit: str


class Document(TarotModel):
    document_id: str
    source: DocumentSource
    file_type: FileType
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str | None = None
    edgar: EdgarMetadata | None = None

    @model_validator(mode="after")
    def _edgar_metadata_matches_source(self) -> Self:
        if (self.source == DocumentSource.EDGAR) != (self.edgar is not None):
            raise ValueError("edgar metadata is required for EDGAR documents and only for them")
        return self
