import uuid
from models.arc import Policy
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from policies.builder import PolicyBuilder
    from data_io.section_extraction import SectionExtractor


class DocumentMetadata(BaseModel):
    """
    Class containing the basic metadata for a document
    """
    title: str
    author: str
    revision: str
    publication_date: date
    num_chapters: int


class TechnicalSpecMetadata(BaseModel):
    """
    Metadata file for tracking technical specification processing state and traceability.
    Stored in output folder to maintain workflow state and enable service integration.
    """
    document_uuid: str = Field(default_factory=lambda: str(uuid.uuid7()),
                               description="UUID7 identifier for this technical specification")
    source_uri: str = Field(..., description="Source URI for the document (e.g., file://path/to/spec.pdf)")
    file_hash: str = Field(..., description="SHA-512 hash of the source file for change detection")
    title: str
    author: str
    revision: str
    publication_date: date
    num_chapters: int
    introduction_file: str | None = None  # Relative path to introduction markdown file
    chapters: list[RawChapterRef] | None = None
    section_policies_generated: dict[str, bool] = Field(default_factory=dict,
                                                        description="Map of section_id -> processing_complete")
    chapter_policies_generated: dict[int, bool] = Field(default_factory=dict,
                                                        description="Map of chapter_number -> processing_complete")
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())
    _save_callback: callable = None

    def set_save_callback(self, callback: callable) -> None:
        """Set callback function to save metadata after updates."""
        self._save_callback = callback

    def mark_chapter_processed(self, chapter_number: int) -> None:
        """Mark a chapter as fully processed (policies created in service)."""
        self.chapter_policies_generated[chapter_number] = True
        self.updated_at = datetime.now()
        if self._save_callback:
            self._save_callback()

    def is_chapter_processed(self, chapter_number: int) -> bool:
        """Check if a chapter has been processed."""
        return self.chapter_policies_generated.get(chapter_number, False)

    def mark_section_processed(self, section_id: str) -> None:
        """ Mark a section as fully processed (single policy correctly created in service)."""
        self.section_policies_generated[section_id] = True
        self.updated_at = datetime.now()
        if self._save_callback:
            self._save_callback()

    def is_section_processed(self, section_id: str) -> bool:
        """Check if a section has been processed."""
        return self.section_policies_generated.get(section_id, False)


class Introduction(BaseModel):
    """
    Initial introduction
    """
    markdown_contents: str


class RawChapter(BaseModel):
    """
    Chapter information
    """
    title: str
    number: int
    markdown_contents: str


class Section(BaseModel):
    """A self-contained section within a chapter that contains policy rules."""
    id: str = Field(..., description="Unique identifier (e.g., 'ch2_sec1')")
    title: str = Field(..., description="Section title/name")
    chapter_number: int = Field(..., description="Parent chapter number")
    markdown_contents: str = Field(..., description="Section content in markdown")


class SectionRef(BaseModel):
    """Reference to a cached section markdown file."""
    id: str
    title: str
    chapter_number: int
    rationale: str
    markdown_file: str  # Path to markdown file


class SectionList(BaseModel):
    sections: list[Section]


class RawChapterRef(BaseModel):
    """Reference to a cached chapter markdown file."""
    title: str
    number: int
    markdown_file: str  # Relative path to markdown file
    sections_extracted: bool = False  # Whether sections have been extracted for this chapter


class Chapter(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str
    number: int
    markdown_contents: str
    policy_builder: Any
    metadata: TechnicalSpecMetadata | None
    section_extractor: Any = None
    _sections: list[Section] | None = None
    _policies: list[Policy] | None = None

    @property
    def sections(self) -> list[Section]:
        """Lazy-load sections from chapter."""
        if self._sections is None:
            if self.section_extractor is None:
                raise RuntimeError(f'section_extractor not set on Chapter {self.number}')
            self._sections = self.section_extractor.extract_sections(self.raw)
        return self._sections

    @property
    def policies(self) -> list[Policy]:
        """Create policies from sections."""
        if self._policies is None:
            # Launch policy builder workflows if they have not been processed
            if not self.metadata.is_chapter_processed(self.number):
                for section in self.sections:
                    if not self.metadata.is_section_processed(section.id):
                        self.policy_builder.process_section(section)
                        self.metadata.mark_section_processed(section.id)

                # Mark chapter as processed in metadata, even if no policies have been created
                self.metadata.mark_chapter_processed(self.number)

            policies = self.policy_builder.get_policies_from_service(self.number)
            self._policies = sorted(policies, key=lambda x: x.name)

        return self._policies

    @property
    def raw(self) -> RawChapter:
        return RawChapter(title=self.title, number=self.number, markdown_contents=self.markdown_contents)

    @classmethod
    def from_raw(cls, raw_chapter: RawChapter, policy_builder: Any,
                 section_extractor: Any = None, metadata: TechnicalSpecMetadata | None = None):
        return cls(title=raw_chapter.title, number=raw_chapter.number, markdown_contents=raw_chapter.markdown_contents,
                   policy_builder=policy_builder, section_extractor=section_extractor, metadata=metadata)
