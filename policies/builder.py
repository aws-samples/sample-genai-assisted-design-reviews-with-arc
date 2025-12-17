import boto3
import base64
import hashlib
import logging
from pathlib import Path
from models.arc import Policy
from misc.config import config
from strands import Agent, tool
from botocore.config import Config
from strands.models import BedrockModel
from strands_tools import file_read, sleep
from models.technical_spec import TechnicalSpecMetadata, Section

bedrock_client = boto3.client('bedrock', region_name=config.region)


class PolicyBuilder:
    def __init__(self, output_dir: Path, metadata: TechnicalSpecMetadata):
        self._output_dir = output_dir
        self._metadata = metadata
        self._document_uuid = metadata.document_uuid
        self._service_policies = None
        tools = [self.create_policy, self.start_workflow, self.get_workflow, file_read, sleep]
        model = BedrockModel(model_id=config.fm_id,
                             boto_client_config=Config(read_timeout=180))
        self.agent = Agent(model=model,
                           system_prompt=r'''You are an agent tasked with converting technical specification documents to formal Bedrock 
                Automated Reasoning Policies and verifying that the resulting policies faithfully represent the criteria described 
                in the original policy. In order to do that:

                * Come up with a policy name that verifies the following regular expression
                  ^[0-9a-zA-Z-_ ]{1,63}\$. and starts with "Ch{:02d}_", where the number denotes the chapter number.
                * Create a new empty Bedrock Automated Reasoning Policy with the name you came out in the previous step, 
                  note its ARN.
                * Start a new Bedrock Automated Reasoning Policy Build Workflow for the policy created in the previous step.
                * Wait for the Automated Reasoning Policy Build Workflow to complete, sleep a little bit if the workflow is 
                  not complete.''', tools=tools)

    def process_section(self, section: Section) -> None:
        """
        Create policies from a single section.

        Parameters
        ----------
        section : Section to process
        """
        print(f'Creating policy for section {section.id}')

        # Execute processing
        self.agent(f'Create a formal policy for the following section in chapter {section.chapter_number}:\n\n'
                   f'<section_title>{section.title}</section_title>\n'
                   f'<section_content>{section.markdown_contents}</section_content>\n'
                   f'<section_id>{section.id}</section_id>')

    @tool(name='create_policy')
    def create_policy(self, policy_name: str, policy_description: str,
                      chapter_number: int, section_id: str) -> dict:
        """
        Creates an Automated Reasoning policy for Amazon Bedrock Guardrails.

        Parameters
        ----------
        policy_name : A unique name for the Automated Reasoning policy
        policy_description: A description of the Automated Reasoning policy. Use this to provide context about the
                            policy's purpose so that an automated system can have the right context when validating
                            conformance of a technical document with the rules in this policy.
                            Maximum length is 1024 characters.
        chapter_number : The chapter number this policy belongs to
        section_id : The ID of the section to maintain traceability

        Returns
        -------
        The details about the created policy
        """
        try:
            # Add tags if document_uuid is available
            tags = [{'key': 'document_uuid', 'value': self._document_uuid},
                    {'key': 'chapter_number', 'value': f'{chapter_number}'},
                    {'key': 'section_id', 'value': section_id}]

            response = bedrock_client.create_automated_reasoning_policy(name=policy_name,
                                                                        description=policy_description,
                                                                        tags=tags)
            del response['ResponseMetadata']
            response['createdAt'] = response['createdAt'].isoformat()
            response['updatedAt'] = response['updatedAt'].isoformat()

            retval = {'toolUseId': f'create_policy-{policy_name}',
                      'status': 'success',
                      'content': [{'text': f'Created policy {policy_name} with ARN {response["policyArn"]}.'},
                                  {'json': response}]}
        except Exception as e:
            logging.exception(e)
            retval = {'toolUseId': f'create_policy-{policy_name}',
                      'status': 'error',
                      'content': [{'text': f'{e}'}]}
        return retval

    @tool(name='start_policy_build_workflow')
    def start_workflow(self, policy_arn: str, document: str,
                       document_name: str = 'SourceDocument.txt') -> dict:
        """
        Start an Amazon Bedrock Automated Reasoning Policy Build Workflow for automatically creating
        rules from context document the easy way.

        Parameters
        ----------
        policy_arn : The ARN for the policy
        document : Markdown-formatted contents of the source document
        document_name : Name of the source document

        Returns
        -------
        The Bedrock Automated Reasoning Policy Build Workflow ID
        """
        source_content = {'workflowContent': {'documents': [{'document': base64.b64encode(document.encode()),
                                                             'documentContentType': 'txt',
                                                             'documentName': document_name}]}}
        source_content['workflowContent']['documents'][0]['documentDescription'] = (
            "You must introduce a special Boolean variable that represents overall, complete compliance with all "
            "relevant aspects of the full Technical Specification.\n"
            "The special variable must be named exactly \"IsCompliantWithFullPolicy\".\n"
            "Every single rule, without exception, must be conditioned on \"IsCompliantWithFullPolicy\".\n")
        crt = hashlib.sha256(document.encode()).hexdigest()
        try:
            response = bedrock_client.start_automated_reasoning_policy_build_workflow(policyArn=policy_arn,
                                                                                      buildWorkflowType='INGEST_CONTENT',
                                                                                      sourceContent=source_content)

            retval = {'toolUseId': f'start_policy_build_workflow-{crt}',
                      'status': 'success',
                      'content': [{'text': f'Created workflow with buildWorkflowId {response["buildWorkflowId"]}'},
                                  {'json': {'buildWorkflowId': response["buildWorkflowId"]}}]}
        except Exception as e:
            logging.exception(e)
            retval = {'toolUseId': f'start_policy_build_workflow-{crt}',
                      'status': 'error',
                      'content': [{'text': f'{e}'}]}
        return retval

    @tool(name='get_policy_build_workflow')
    def get_workflow(self, policy_arn: str, build_workflow_id: str) -> dict:
        """
        Retrieves detailed information about an Automated Reasoning policy build workflow,
        including its status, configuration, and metadata.

        Parameters
        ----------
        policy_arn : The ARN for the policy
        build_workflow_id : The unique identifier of the build workflow to retrieve.

        Returns
        -------
        The detailed information about the policy build workflow
        """
        try:
            response = bedrock_client.get_automated_reasoning_policy_build_workflow(policyArn=policy_arn,
                                                                                    buildWorkflowId=build_workflow_id)
            del response['ResponseMetadata']
            response['createdAt'] = response['createdAt'].isoformat()
            response['updatedAt'] = response['updatedAt'].isoformat()

            retval = {'toolUseId': f'get_policy_build_workflow-{build_workflow_id}',
                      'status': 'success',
                      'content': [{'text': f'Workflow with buildWorkflowId {response["buildWorkflowId"]} '
                                           f'is in status {response["status"]} since {response["updatedAt"]}.'},
                                  {'json': response}]}
        except Exception as e:
            retval = {'toolUseId': f'get_policy_build_workflow-{build_workflow_id}',
                      'status': 'error',
                      'content': [{'text': f'{e}'}]}
        return retval

    def get_policies_from_service(self, chapter_number: int, force_refresh: bool = False) -> list[Policy]:
        """
        Query Bedrock AR service for existing policies matching document UUID and chapter number.
        Returns the latest version of each policy.
        """
        if not self._document_uuid:
            return []

        # List all policies with pagination
        if self._service_policies is None or force_refresh:
            logging.debug('Fetching all policies from the Bedrock ARc service...')
            self._service_policies = {'tags': {},
                                      'policies': {}}
            all_policies = {}
            # Fetch the policy summaries
            next_token = None
            while True:
                kwargs = {'maxResults': 100}
                if next_token:
                    kwargs['nextToken'] = next_token

                response = bedrock_client.list_automated_reasoning_policies(**kwargs)
                for summary in response['automatedReasoningPolicySummaries']:
                    all_policies[summary['policyArn']] = summary

                next_token = response.get('nextToken')
                if not next_token:
                    break

            # Fetch the tags per policy and store the policies that apply to this document
            for policy_arn in all_policies:
                tags_response = bedrock_client.list_tags_for_resource(resourceARN=policy_arn)
                tags = {tag['key']: tag['value'] for tag in tags_response.get('tags', [])}
                if tags.get('document_uuid') == self._document_uuid:
                    self._service_policies['tags'][policy_arn] = tags

            # Finally, retrieve the definitions for the latest versions of the policies
            for policy_arn in self._service_policies['tags']:
                versions = []
                next_token = None

                while True:
                    kwargs = {'policyArn': f'{policy_arn}', 'maxResults': 100}
                    if next_token:
                        kwargs['nextToken'] = next_token

                    versions_response = bedrock_client.list_automated_reasoning_policies(**kwargs)
                    versions.extend(versions_response.get('automatedReasoningPolicySummaries', []))

                    next_token = versions_response.get('nextToken')
                    if not next_token:
                        break

                if versions:
                    # Sort by version and get latest
                    latest_version = max(versions, key=lambda v: -1 if v['version'] == 'DRAFT' else int(v['version']))
                    version_id = latest_version['version']

                    # Get full policy definition, needed as we want to have the policy definition hash
                    versioned_policy_arn = policy_arn if version_id == 'DRAFT' else f'{policy_arn}:{version_id}'
                    policy_data = bedrock_client.get_automated_reasoning_policy(
                        policyArn=versioned_policy_arn
                    )

                    # Retrieve policy definition
                    print(f'Retrieving definition for policy {policy_arn}')
                    policy_definition = self._export_policy_definition(policy_arn, latest_version)

                    policy = Policy.from_service_response(policy_data, policy_definition)
                    self._service_policies['policies'][policy_arn] = policy

        return sorted([policy for arn, policy in self._service_policies['policies'].items()
                       if self._service_policies['tags'][arn]['chapter_number'] == f'{chapter_number}'],
                      key=lambda p: p.name)

    @staticmethod
    def _export_policy_definition(policy_arn: str, latest_version: dict) -> str:
        """
        Export policy definition, working around AWS bug where DRAFT-only policies return empty.

        Parameters
        ----------
        policy_arn : The policy ARN
        latest_version : The latest version summary dict

        Returns
        -------
        Policy definition as string
        """
        # Retrieve the policy differently depending on whether the DRAFT version is the only one
        if latest_version['version'] == 'DRAFT':
            # Workaround: Get definition from build workflow artifacts
            logging.debug(f'Only DRAFT version available for {policy_arn}, using build artifacts workaround')

            # List build workflows for this policy
            workflows = []
            next_token = None
            while True:
                kwargs = {'policyArn': policy_arn, 'maxResults': 100}
                if next_token:
                    kwargs['nextToken'] = next_token

                response = bedrock_client.list_automated_reasoning_policy_build_workflows(**kwargs)
                workflows.extend(response.get('automatedReasoningPolicyBuildWorkflowSummaries', []))

                next_token = response.get('nextToken')
                if not next_token:
                    break

            if not workflows:
                raise RuntimeError(f'No build workflows found for policy {policy_arn}')

            # Get latest workflow (most recent createdAt)
            latest_workflow = max(workflows, key=lambda w: w['createdAt'])
            build_workflow_id = latest_workflow['buildWorkflowId']

            # Retrieve policy definition from build artifacts
            result = bedrock_client.get_automated_reasoning_policy_build_workflow_result_assets(
                policyArn=policy_arn,
                buildWorkflowId=build_workflow_id,
                assetType='POLICY_DEFINITION'
            )

            return result['buildWorkflowAssets']['policyDefinition']
        else:
            # Use standard export API for published versions
            versioned_policy_arn = f'{policy_arn}:{latest_version['version']}'

            policy_definition = bedrock_client.export_automated_reasoning_policy_version(
                policyArn=versioned_policy_arn
            )
            return policy_definition['policyDefinition']
