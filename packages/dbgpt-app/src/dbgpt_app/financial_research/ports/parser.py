"""Document parsing port."""

from pathlib import Path
from typing import Optional, Protocol

from ..domain.models import ParsedDocument, ResearchSource


class DocumentParser(Protocol):
    def supports(self, path: Path) -> bool: ...

    def parse(
        self, source: ResearchSource, enable_ocr: Optional[bool] = None
    ) -> ParsedDocument:
        """Parse one source.

        ``enable_ocr`` overrides the adapter's default for this call only, so a
        single request can opt into recognizing a scanned filing without
        changing the behaviour of the shared registry.
        """
        ...
