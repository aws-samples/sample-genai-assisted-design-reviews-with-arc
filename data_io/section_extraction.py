"""Section extraction from chapter markdown."""

import json
import logging
from pathlib import Path
from strands import Agent
from misc.config import config
from strands.models import BedrockModel
from botocore.config import Config as BotocoreConfig
from models.technical_spec import TechnicalSpecMetadata, RawChapter, Section, SectionList

logger = logging.getLogger(__name__)


class SectionExtractor:
    """Extracts policy-relevant sections from chapter markdown."""

    def __init__(self, cache_path: Path = None):
        model = BedrockModel(
            model_id=config.fm_id,
            boto_client_config=BotocoreConfig(read_timeout=180)
        )

        system_prompt = """You are an expert at analyzing technical specification documents and identifying self-contained sections that contain policy rules or technical requirements.

Your task is to:
1. Identify sections within the chapter that contain verifiable technical requirements or policy rules
2. Ignore introductory text, version control information, and non-policy content
3. Ensure each section is self-contained (can be understood independently)
4. Provide clear rationale for why each section boundary was chosen
5. Generate meaningful, descriptive titles for each section

Guidelines:
- A section should focus on a specific topic or requirement area
- Sections should be substantial enough to contain meaningful policies (not single sentences)
- Avoid creating too many tiny sections or too few large sections
- If a chapter has no policy content, return an empty list
- Section titles should be concise but descriptive (max 100 characters)

Output a list of Section objects with proper structure."""

        self.agent = Agent(model=model, system_prompt=system_prompt)
        self.cache_path = cache_path

    def extract_sections(self, chapter: RawChapter) -> list[Section]:
        """
        Extract sections from a chapter with caching.
        
        Parameters
        ----------
        chapter : The chapter to extract sections from
        
        Returns
        -------
        List of Section objects
        """
        # Try loading from techspec metadata if available
        if self.cache_path and self.cache_path.exists():
            try:
                cache_data = json.loads(self.cache_path.read_text())
                metadata = TechnicalSpecMetadata(**cache_data)

                # Find chapter in metadata
                if metadata.chapters:
                    chapter_ref = next((c for c in metadata.chapters if c.number == chapter.number), None)
                    if chapter_ref and chapter_ref.sections_extracted:
                        # Load sections by scanning the chapter directory
                        chapter_dir = config.output_dir / f"chapter_{chapter.number:02d}"
                        if chapter_dir.exists():
                            sections = []
                            section_files = sorted(chapter_dir.glob("section_*.md"))
                            
                            for section_file in section_files:
                                section_id = f"ch{chapter.number}_{section_file.stem}"
                                section = Section(
                                    id=section_id,
                                    title=section_file.stem.replace('_', ' ').title(),
                                    chapter_number=chapter.number,
                                    markdown_contents=section_file.read_text()
                                )
                                sections.append(section)
                            
                            if sections:
                                logger.info(f'Loaded {len(sections)} sections from cache for chapter {chapter.number}')
                                return sections
            except Exception as e:
                logger.warning(f'Failed to load sections from techspec metadata: {e}')

        # Extract sections using agent
        logger.info(f'Extracting sections from chapter {chapter.number}: {chapter.title}')

        prompt = f"""Analyze the following chapter and extract self-contained sections that contain policy rules or technical requirements.

Chapter {chapter.number}: {chapter.title}

<chapter_content>
{chapter.markdown_contents}
</chapter_content>

Extract sections with clear boundaries and rationale. Each section should have:
- A unique ID in format "ch{chapter.number}_sec{{N}}"
- A descriptive title
- The chapter number ({chapter.number})
- The markdown content for that section
- A rationale explaining why this is a self-contained section

Return a list of Section objects."""

        sections = self.agent(prompt, structured_output_model=SectionList).structured_output.sections
        logger.info(f'Extracted {len(sections)} sections for chapter {chapter.number}')

        return sections
