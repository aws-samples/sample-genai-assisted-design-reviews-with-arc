"""Document processing service with proper error handling and validation."""

import json
import boto3
import hashlib
import logging
from pathlib import Path
from strands import Agent
from datetime import datetime
from misc.config import config
from models.arc import ResolvedPolicy
from strands.models import BedrockModel
from policies.builder import PolicyBuilder
from botocore.config import Config as BotocoreConfig
from data_io.html_report import generate_html_report
from data_io.section_extraction import SectionExtractor
from strands.types.content import ContentBlock, CachePoint
from models.technical_spec import DocumentMetadata, TechnicalSpecMetadata, Introduction, RawChapter, Section, \
    RawChapterRef, Chapter

logger = logging.getLogger(__name__)


class TechnicalSpec:
    """PDF-based Technical Spec document handling."""

    def __init__(self, file_path: Path):
        # Validate input file
        if not file_path.is_file():
            raise RuntimeError(f"Cannot read input PDF file: {file_path}")

        # Check file size
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > config.max_document_size_mb:
            raise RuntimeError(f"File too large: {file_size_mb:.1f}MB "
                               f"(max: {config.max_document_size_mb}MB)")

        self.file_path = file_path

        # Internal structures that will be lazy-loaded
        self._num_chapters = None
        self._introduction: Introduction | None = None
        self._chapters: list[Chapter] | None = None
        self._title = None
        self._author = None
        self._revision = None
        self._publication_date = None
        self._consolidated_text: str | None = None
        self._metadata: TechnicalSpecMetadata | None = None

        # Calculate file hash for caching
        self.file_hash = hashlib.sha512(self.file_path.read_bytes()).hexdigest()
        self._metadata_path = config.output_dir / f'{file_path.stem}.metadata.json'

        # Agent-related stuff
        self._agent = None
        self._compliance_agents = {}
        self.policy_builder = PolicyBuilder(output_dir=config.output_dir,
                                            metadata=self.metadata)
        self.section_extractor = SectionExtractor(cache_path=self._metadata_path)

        # Load from cache if available
        self._load_from_cache()

    @property
    def metadata(self) -> TechnicalSpecMetadata:
        """Lazy-load or create metadata for this technical specification."""
        if self._metadata is None:
            if self._metadata_path.exists():
                try:
                    data = json.loads(self._metadata_path.read_text())
                    self._metadata = TechnicalSpecMetadata(**data)
                    # Update hash if file changed
                    if self._metadata.file_hash != self.file_hash:
                        logger.warning(f"File hash mismatch, updating metadata")
                        self._metadata.file_hash = self.file_hash
                        self._metadata.updated_at = datetime.now()
                        self._save_metadata()
                except Exception as e:
                    logger.warning(f"Failed to load metadata: {e}, creating new")
                    self._metadata = None

            if self._metadata is None:
                # Create new metadata
                self._metadata = TechnicalSpecMetadata(
                    source_uri=f"file://{self.file_path.absolute()}",
                    file_hash=self.file_hash,
                    title=self.title,
                    author=self.author,
                    revision=self.revision,
                    publication_date=self.publication_date,
                    num_chapters=self.num_chapters
                )
                self._save_metadata()

            # Set save callback
            self._metadata.set_save_callback(self._save_metadata)

        return self._metadata

    def _save_metadata(self) -> None:
        """Save metadata to disk."""
        self._metadata_path.write_text(self._metadata.model_dump_json(indent=2))

    @property
    def agent(self) -> Agent:
        if self._agent is None:
            transcription_prompt = """# PDF to Engineering-Accurate Markdown Conversion Task
    
            ## Objective
            Convert the input PDF file into a precise Markdown format that preserves all engineering details for automated formal 
            rule-extraction processing. The system only accepts text input, so your conversion must maintain complete fidelity to 
            the original document's technical content.
    
            ## Conversion Guidelines
    
            ### Text Content
            - Preserve all original text content exactly as written
            - Apply appropriate Markdown formatting (headers, emphasis, lists, etc.) without altering the original meaning
            - Maintain all technical terminology, equations, references, and specialized notation
            - Keep paragraph structure and logical flow intact

            ### Images and Diagrams
            - Provide detailed, engineering-accurate descriptions of all visual elements, including specific attributes described 
              in the diagrams, such as component categories and operational characteristics, as well as their amount.
            - Include all measurements, labels, connections, and technical specifications shown
            - Describe any color coding, symbols, or notation systems used
            - Highlight elements referenced elsewhere in the document
            - Structure descriptions logically (e.g., "This circuit diagram shows... with components A, B, and C connected to...")
    
            ### Processing Instructions
            - Process the document chapter by chapter
            - Output only one complete chapter per iteration to avoid token limitations
            - Indicate chapter numbers and section hierarchy clearly
            - Use consistent Markdown header levels to maintain document structure
    
            Please convert the PDF content following these guidelines, ensuring that an engineer reading your Markdown version 
            would have access to the same complete technical information as in the original document.
    
            Provide your conversion output without any preamble or additional explanations beyond the converted Markdown content."""

            model = BedrockModel(model_id=config.fm_id,
                                 boto_client_config=BotocoreConfig(read_timeout=180))
            self._agent = Agent(model=model,
                                system_prompt=transcription_prompt)

            # Send the document contents to the agent for later use
            self._agent([ContentBlock(document={'format': 'pdf',
                                                'name': self.file_path.stem,
                                                'source': {'bytes': self.file_path.read_bytes()}}),
                         ContentBlock(
                             text=f'This document is named "{self.file_path.stem}" and contains the technical '
                                  'specification I need you to work on. Whenever I talk about the technical '
                                  f'specification or "{self.file_path.stem}", I\'m referring to this PDF document. '
                                  'Confirm with a single word that you have understood this.'),
                         ContentBlock(cachePoint=CachePoint(type='default'))])
            logger.info("Transcription agent initialized successfully")
            # self._agent.conversation_manager.checkpoint(self._agent)

        return self._agent

    @property
    def num_chapters(self) -> int:
        if self._num_chapters is None:
            self._process_document_metadata()

        return self._num_chapters

    @property
    def introduction(self) -> Introduction:
        if self._introduction is None:
            self._process_document()

        return self._introduction

    @property
    def chapters(self) -> list[Chapter]:
        if self._chapters is None or len(self._chapters) < self.num_chapters:
            self._process_document()

        return self._chapters

    @property
    def title(self) -> str:
        if self._title is None:
            self._process_document_metadata()

        return self._title

    @property
    def author(self) -> str:
        if self._author is None:
            self._process_document_metadata()

        return self._author

    @property
    def revision(self) -> str:
        if self._revision is None:
            self._process_document_metadata()

        return self._revision

    @property
    def publication_date(self) -> datetime:
        if self._publication_date is None:
            self._process_document_metadata()

        return self._publication_date

    @property
    def consolidated_text(self) -> str:
        if self._consolidated_text is None:
            self._process_document()

        return self._consolidated_text

    def to_html_report(self, resolved_policies: list[ResolvedPolicy], output_path: Path) -> None:
        """
        Generate an HTML report showing resolved policies with embedded documents.
        
        Parameters
        ----------
        resolved_policies : List of resolved policies from check_compliance()
        output_path : Path where the HTML report will be saved
        """
        # Organize resolved policies by chapter
        policy_map = {p.id: p for p in resolved_policies}
        chapters_data = []
        for chapter in self.chapters:
            chapter_policies = [policy_map[p.id] for p in chapter.policies if p.id in policy_map]
            if chapter_policies:
                chapters_data.append((f"Chapter {chapter.number}: {chapter.title}", chapter_policies))

        generate_html_report(self.title, self.file_path, chapters_data, output_path)

    def check_compliance(self, proposal_paths: list[Path]) -> list[ResolvedPolicy]:
        """
        Check compliance of a proposal document against the technical specification.
        
        Parameters
        ----------
        proposal_paths : list of Paths to the documents that compose the proposal
        
        Returns
        -------
        ComplianceReport containing detailed compliance information
        """
        if len(proposal_paths) > 5:
            raise RuntimeError('Cannot parse more than 5 documents in a single proposal')

        for p in proposal_paths:
            if not p.is_file():
                raise RuntimeError(f'Cannot read proposal file: {p}')

        # Calculate cache key from proposal contents
        proposal_hash = hashlib.sha512(b''.join(p.read_bytes() for p in proposal_paths)).hexdigest()

        resolved_policies = []
        for chapter in self.chapters:
            print(f'Processing policy chapter {chapter.number} - {chapter.title}')
            for policy in chapter.policies:
                if len(policy.variables) == 0:
                    print(f'\tSkipping empty policy {policy.name}')
                    continue
                print(f'\tProcessing policy {policy.name}')
                # Calculate cache key for this specific policy + proposal combination
                hash_key = hashlib.sha512(f'{proposal_hash}_{policy.id}_{policy.definition_hash}'.encode()).hexdigest()
                cache_path = config.cache_dir / f'resolved_policy_{hash_key}.json'

                # Try loading from cache
                if cache_path.exists():
                    try:
                        cache_data = json.loads(cache_path.read_text())
                        resolved_policy = ResolvedPolicy(**cache_data)
                        logging.debug(f'Loaded compliance result from cache: {cache_path}')
                        resolved_policies.append(resolved_policy)
                        continue
                    except Exception as e:
                        logging.debug(f'Failed to load compliance cache: {e}, regenerating')

                # Resolve the variables in the policy for the given proposal
                resolved_policy = policy.resolve_vars(proposal_paths)
                resolved_vars = [v for v in resolved_policy.variables
                                 if v.value is not None and v.name != 'IsCompliantWithFullPolicy']
                if not resolved_vars:
                    resolved_policy.ar_assessment = [{'notApplicable': {}}]
                else:
                    # Try to avoid TOO_COMPLEX policy errors by reducing the amount
                    # of characters sent to the model
                    warned = False
                    while True:
                        assigned_vars = {'premises': {v.name: v.value for v in resolved_vars},
                                         'claims': {'IsCompliantWithFullPolicy': 'true'}}
                        serialized = json.dumps(assigned_vars, separators=(',', ':')).replace('"', '')
                        if len(serialized) > 400:
                            if not warned:
                                warned = True
                                logging.warning('Evaluating the policy with a reduced set of variables to '
                                                'try to get results from the system')
                            resolved_vars = resolved_vars[:-1]
                            continue
                        break
                    # Ask ARc about the assigned vars, obtain their findings
                    bedrock_client = boto3.client(service_name='bedrock-runtime', region_name=config.region)
                    content = [{'text': {'text': serialized,
                                         "qualifiers": ["guard_content"]}}]
                    logging.debug(f'Evaluating {policy.name} guardrail against the set of assigned variables\n' +
                                  json.dumps(assigned_vars, indent=2))
                    response = bedrock_client.apply_guardrail(guardrailIdentifier=policy.guardrail.id,
                                                              guardrailVersion=policy.guardrail.version,
                                                              content=content,
                                                              outputScope='FULL',
                                                              source='OUTPUT')
                    findings = response['assessments'][0]['automatedReasoningPolicy']['findings']
                    resolved_policy.ar_assessment = findings
                resolved_policies.append(resolved_policy)

                # Save to cache
                try:
                    cache_path.write_text(resolved_policy.model_dump_json(indent=2))
                    print(f'Saved compliance result to cache: {cache_path}')
                except Exception as e:
                    print(f'Failed to save compliance cache: {e}')

        return resolved_policies

    def _process_document(self) -> None:
        """
        Extract document contents.
        """
        self._process_document_metadata()

        # Initialize if needed
        if self._introduction is None:
            self._introduction = self._get_chapter(0)

        if self._chapters is None:
            self._chapters = []

        if self._consolidated_text is None:
            self._consolidated_text = self._introduction.markdown_contents + '\n\n'

        # Determine which chapters still need to be extracted
        start_chapter = len(self._chapters) + 1

        # Extract remaining chapters
        for i in range(start_chapter - 1, self.num_chapters):
            chapter = self._get_chapter(i + 1)
            self._chapters.append(chapter)
            self._consolidated_text += chapter.markdown_contents + '\n\n'
            self._save_to_cache()

        self._save_to_cache()

    def _process_document_metadata(self) -> None:
        """
        Extract document structure information.
        """
        # Only execute the metadata extraction once
        if self._title is None:
            logger.debug(f"Extracting structure from: {self.file_path}")

            structure = self._get_document_metadata()
            self._title = structure.title
            self._author = structure.author
            self._revision = structure.revision
            self._publication_date = structure.publication_date
            self._num_chapters = structure.num_chapters

            self._save_to_cache()

    def _get_chapter(self, num: int) -> Introduction | Chapter:
        """Get chapter with retry logic."""
        print(f'Getting chapter {num}, agent has {len(self.agent.messages)} messages stored')
        if num == 0:
            return self.agent.structured_output(Introduction,
                                                'Convert the contents of everything before chapter '
                                                '1 in the technical specification to Markdown. '
                                                'Provide only the converted Markdown text '
                                                'without any explanations, comments, or '
                                                'descriptions of your process. Do not include '
                                                'phrases like "Here\'s the converted '
                                                'text:" or "The Markdown version is:".')

        return Chapter.from_raw(self.agent.structured_output(RawChapter,
                                                             f'Convert the contents of chapter {num} in the '
                                                             'technical specification to Markdown. Provide only the '
                                                             'converted Markdown text without any explanations, '
                                                             'comments, or descriptions of your process. Do not '
                                                             'include phrases like "Here\'s the converted text:" '
                                                             'or "The Markdown version is:".'),
                                policy_builder=self.policy_builder,
                                section_extractor=self.section_extractor,
                                metadata=self.metadata)

    def _get_document_metadata(self) -> DocumentMetadata:
        """Get document metadata with retry logic."""
        return self.agent(f'Extract the metadata from {self.file_path.stem}',
                          structured_output_model=DocumentMetadata).structured_output

    def _load_sections_from_files(self, chapter_number: int) -> list[Section]:
        """Helper to load sections from markdown files by scanning the chapter directory."""
        chapter_dir = config.output_dir / f"chapter_{chapter_number:02d}"
        if not chapter_dir.exists():
            return []

        sections = []

        # Find all section_*.md files in the chapter directory
        section_files = sorted(chapter_dir.glob("section_*.md"))

        for section_file in section_files:
            try:
                # Generate section metadata from filename and content
                section_id = f"ch{chapter_number}_{section_file.stem}"
                section = Section(
                    id=section_id,
                    title=section_file.stem.replace('_', ' ').title(),
                    chapter_number=chapter_number,
                    markdown_contents=section_file.read_text()
                )
                sections.append(section)
            except Exception as e:
                logger.warning(f"Failed to load section {section_file}: {e}")

        return sections

    def _load_from_cache(self) -> None:
        """Load cached data from output folder."""
        if not self._metadata_path.exists():
            return

        if self.metadata.file_hash != self.file_hash:
            return

        self._title = self.metadata.title
        self._author = self.metadata.author
        self._revision = self.metadata.revision
        self._publication_date = self.metadata.publication_date
        self._num_chapters = self.metadata.num_chapters

        # Load introduction
        if self.metadata.introduction_file:
            intro_path = config.output_dir / self.metadata.introduction_file
            if intro_path.exists():
                self._introduction = Introduction(markdown_contents=intro_path.read_text())

        # Load chapters
        if self.metadata.chapters:
            self._chapters = []
            for chapter_ref in self.metadata.chapters:
                chapter_path = config.output_dir / chapter_ref.markdown_file
                if not chapter_path.exists():
                    continue

                raw_chapter = RawChapter(
                    title=chapter_ref.title,
                    number=chapter_ref.number,
                    markdown_contents=chapter_path.read_text()
                )
                chapter = Chapter.from_raw(raw_chapter,
                                           policy_builder=self.policy_builder,
                                           section_extractor=self.section_extractor,
                                           metadata=self.metadata)

                # Load sections by scanning directory
                if chapter_ref.sections_extracted:
                    sections = self._load_sections_from_files(chapter_ref.number)
                    chapter._sections = sections if sections else []

                self._chapters.append(chapter)

        # Rebuild consolidated text
        if self._introduction:
            self._consolidated_text = self._introduction.markdown_contents + '\n\n'
            if self._chapters:
                for chapter in self._chapters:
                    self._consolidated_text += chapter.markdown_contents + '\n\n'

        logger.debug(f"Loaded cached data for {self.file_path}")

    def _save_to_cache(self) -> None:
        """Save current state to metadata file."""
        if all(x is not None for x in [self._title, self._author, self._revision,
                                       self._publication_date, self._num_chapters]):
            try:
                # Save introduction to file
                introduction_file = None
                if self._introduction:
                    intro_path = config.output_dir / "introduction.md"
                    intro_path.write_text(self._introduction.markdown_contents)
                    introduction_file = "introduction.md"

                # Save chapters to hierarchical structure
                chapter_refs = None
                if self._chapters:
                    chapter_refs = []
                    for chapter in self._chapters:
                        chapter_dir = config.output_dir / f"chapter_{chapter.number:02d}"
                        chapter_dir.mkdir(exist_ok=True)

                        # Save chapter markdown
                        chapter_md_path = chapter_dir / "chapter.md"
                        chapter_md_path.write_text(chapter.markdown_contents)

                        # Save section markdowns (no references stored in cache)
                        for i, section in enumerate(chapter.sections, 1):
                            section_path = chapter_dir / f"section_{i:02d}.md"
                            section_path.write_text(section.markdown_contents)

                        chapter_refs.append(RawChapterRef(
                            title=chapter.title,
                            number=chapter.number,
                            markdown_file=f"chapter_{chapter.number:02d}/chapter.md",
                            sections_extracted=True
                        ))

                # Update metadata
                metadata = self.metadata
                metadata.file_hash = self.file_hash
                metadata.title = self._title
                metadata.author = self._author
                metadata.revision = self._revision
                metadata.publication_date = self._publication_date
                metadata.num_chapters = self._num_chapters
                metadata.introduction_file = introduction_file
                metadata.chapters = chapter_refs
                metadata.updated_at = datetime.now()

                self._save_metadata()
                logger.warning(f'Saved metadata for {self.file_path}')
            except Exception as e:
                logger.exception(e)
