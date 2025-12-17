#!/usr/bin/env python3

import logging
from pathlib import Path
from misc.config import config
from policies.documents import TechnicalSpec

# Configure the root strands logger
# logging.getLogger("strands").setLevel(logging.DEBUG)

# Add a handler to see the logs
logging.basicConfig(format="%(levelname)s | %(name)s | %(message)s",
                    handlers=[logging.StreamHandler()])


def extract_sections(spec_path: Path, output_dir: Path):
    """Convert technical specification PDF to Markdown and extract sections."""
    config.output_dir = output_dir
    doc = TechnicalSpec(file_path=spec_path)
    print(f"Sections extracted to: {output_dir}")
    for i, chapter in enumerate(doc.chapters):
        print(f'\tChapter {i + 1} ({len(chapter.sections)} sections): {chapter.title}')


def create_policies(spec_path: Path, transcription_dir: Path):
    """Extract formal policies from technical specification and store in Bedrock service."""
    config.output_dir = transcription_dir
    doc = TechnicalSpec(file_path=spec_path)

    # Access chapters to trigger policy creation
    for chapter in doc.chapters:
        print(f"Processing Chapter {chapter.number}: {chapter.title}")
        policies = chapter.policies
        print(f"  Chapter contains {len(policies)} policies")

    print(f"\nPolicies stored in Bedrock service with document UUID: {doc.metadata.document_uuid}")


def evaluate_proposal(spec_path: Path, proposal_paths: list[Path], output_path: Path, transcription_dir: Path):
    """Evaluate proposals against technical specification and generate HTML compliance report."""
    config.output_dir = transcription_dir
    doc = TechnicalSpec(file_path=spec_path)

    resolved_policies = doc.check_compliance(proposal_paths)
    doc.to_html_report(resolved_policies, output_path)
    print(f"\nCompliance report generated: {output_path}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Bedrock Automated Reasoning-powered design review assistant')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # extract-sections subcommand
    extract_parser = subparsers.add_parser('extract-sections', help='Extract sections from technical specification')
    extract_parser.add_argument('--spec', type=Path, required=True, help='Path to technical specification PDF')
    extract_parser.add_argument('--transcription-dir', type=Path, required=True,
                                help='Directory for transcription output')

    # create-policies subcommand
    policies_parser = subparsers.add_parser('create-policies', help='Create policies from technical specification')
    policies_parser.add_argument('--spec', type=Path, required=True, help='Path to technical specification PDF')
    policies_parser.add_argument('--transcription-dir', type=Path, required=True,
                                 help='Directory containing transcriptions')

    # evaluate-proposal subcommand
    evaluate_parser = subparsers.add_parser('evaluate-proposal',
                                            help='Evaluate proposals against technical specification')
    evaluate_parser.add_argument('--spec', type=Path, required=True, help='Path to technical specification PDF')
    evaluate_parser.add_argument('--proposals', type=Path, nargs='+', required=True, help='Paths to 1-4 proposal PDFs')
    evaluate_parser.add_argument('--output', type=Path, required=True, help='Path for HTML report output')
    evaluate_parser.add_argument('--transcription-dir', type=Path, required=True,
                                 help='Directory containing transcriptions')

    args = parser.parse_args()

    if args.command == 'extract-sections':
        extract_sections(args.spec, args.transcription_dir)
    elif args.command == 'create-policies':
        create_policies(args.spec, args.transcription_dir)
    elif args.command == 'evaluate-proposal':
        if len(args.proposals) > 4:
            parser.error('Maximum 4 proposal documents allowed')
        evaluate_proposal(args.spec, args.proposals, args.output, args.transcription_dir)
