import json
import uuid
import boto3
import hashlib
import logging
from pathlib import Path
from strands import Agent
from typing import Literal
from typing import Optional
from datetime import datetime
from misc.config import config
from models.bedrock import Guardrail
from models.findings import ARCFinding
from pydantic import BaseModel, Field, PrivateAttr, create_model
from strands.types.content import ContentBlock, CachePoint

logger = logging.getLogger(__name__)


class TypeValue(BaseModel):
    value: str = Field(..., description='The actual value or identifier for this type value',
                       min_length=1, max_length=64)
    description: str = Field(..., description='A human-readable description explaining what this type '
                                              'value represents and when it should be used.',
                             min_length=0, max_length=1024)


class BaseType(BaseModel):
    name: str = Field(..., description='The name of the custom type.')
    description: str = Field(..., description='The description of what the custom type represents')


class Type(BaseType):
    values: list[TypeValue] = Field(..., description='The possible values for this enum-based type, '
                                                     'each with its own description')


class Variable(BaseModel):
    """
    Represents a variable used in a rule definition
    """
    name: str = Field(..., description='The name of the variable')
    type: BaseType = Field(..., description='The data type of the variable. Valid types include bool, int, '
                                            'real, enum, and custom types that you can provide.')
    description: str = Field(..., description='The description of the variable that explains what it '
                                              'represents and how users might refer to it.')


class Rule(BaseModel):
    """
    Represents a formal policy rule.
    """
    id: str = Field(..., description="Unique identifier for the rule")
    expression: str = Field(..., min_length=1, description="The formal rule definition")
    alternate_expression: str = Field(..., min_length=1, description='Alternative version of the rule')
    variables: list[Variable] = Field(..., description='List of variables that are part of this rule')


class Policy(BaseModel):
    """
    A formal policy containing several rules
    """
    name: str
    arn: str | None
    id: str
    description: str
    definition_hash: str
    version: str
    types: list[BaseType]
    variables: list[Variable]
    rules: list[Rule]
    _guardrail: Guardrail | None = None

    @property
    def versioned_arn(self):
        if self.arn is None:
            return None
        elif self.version == 'DRAFT':
            return self.arn

        return f'{self.arn}:{self.version}'

    def resolve_vars(self, proposal_paths: list[Path]) -> ResolvedPolicy:
        """
        Resolve the values of the variables in the policy by querying the technical spec document(s)
        """
        # Calculate cache key from proposal contents & policy definition hash
        proposal_hash = hashlib.sha512(b''.join(p.read_bytes() for p in proposal_paths)).hexdigest()
        hash_key = hashlib.sha512(f'{proposal_hash}_{self.id}'.encode()).hexdigest()
        cache_path = config.cache_dir / f'resolved_policy_{hash_key}.json'

        # Try loading from cache
        if cache_path.exists():
            try:
                cache_data = json.loads(cache_path.read_text())
                logger.debug(f'Loaded resolved policy from cache: {cache_path}')
                return ResolvedPolicy(**cache_data)
            except Exception as e:
                logger.warning(f'Failed to load cache: {e}')

        # Create the var resolver agent
        var_resolver = Agent(model=config.fm_id,
                             system_prompt='''# Technical Document Parameter Extractor

        You are an AI agent in an automated system that analyzes technical proposal documents for adherence to specifications. 
        Your specific task is to extract values of design parameters from technical proposals based on their definitions.

        The end goal of the system is to check the proposal's adherence to a Technical Specification, so be sure to review your
        answers and be as factual as possible, even if that means providing a range of values when the exact value of a variable
        can not be determined but a range can or `null` if the value cannot be found in the technical proposal document.

        When looking for variable values, you will be provided with a context. Only provide responses extracted from the 
        sections of the technical proposal that are relevant to that context.''')

        # Resolve variables
        vars_model = self._vars_to_model()
        prompt = []
        n_docs = len(proposal_paths)
        for i, p in enumerate(proposal_paths, 1):
            name = f'Proposal doc_{i}'
            prompt.extend([ContentBlock(document={'format': 'pdf',
                                                  'name': name,
                                                  'source': {'bytes': p.read_bytes()}}),
                           ContentBlock(text=f'"{name}" contains the vendor-supplied proposal '
                                             f'(part {i}/{n_docs}) that should be used as the source of '
                                             'truth for extracting the values of the parameters below.')])
        prompt.append(ContentBlock(cachePoint=CachePoint(type='default')))
        prompt.append(ContentBlock(text='Extract the values of the proposal parameters in the context '
                                        'of a policy evaluating the following aspects of an associated '
                                        'technical specification:\n\n'
                                        f'\t{self.description}\n\n'
                                        'If you cannot extract the value for a variable, just provide '
                                        'a null value.'))
        parameters = var_resolver(prompt, structured_output_model=vars_model).structured_output

        resolved_vars = []
        for var in self.variables:
            value = getattr(parameters, var.name, None)
            if value is None:
                resolved_vars.append(ResolvedVariable(name=var.name, type=var.type,
                                                      description=var.description,
                                                      value=None))
            else:
                resolved_vars.append(ResolvedVariable(name=var.name, type=var.type,
                                                      description=var.description,
                                                      value=f'{value}'))

        resolved_rules = [ResolvedRule(id=rule.id,
                                       expression=rule.expression,
                                       alternate_expression=rule.alternate_expression,
                                       variables=[rv for rv in resolved_vars if rv.name in rule.expression.split()])
                          for rule in self.rules]

        resolved_policy = ResolvedPolicy(name=self.name, arn=self.arn, id=self.id, description=self.description,
                                         definition_hash=self.definition_hash, version=self.version,
                                         types=self.types, variables=resolved_vars,
                                         rules=resolved_rules, proposal_paths=proposal_paths)

        # Save to cache
        try:
            cache_path.write_text(resolved_policy.model_dump_json(indent=2))
            logger.debug(f'Saved resolved policy to cache: {cache_path}')
        except Exception as e:
            logger.warning(f'Failed to save cache: {e}')

        return resolved_policy

    def _vars_to_model(self) -> BaseModel:
        # Create a custom model, we'll use that for extracting the values of the variables
        kwargs = {}
        type_map = {'BOOL': bool, 'INT': int, 'NUMBER': float}
        for var in self.variables:
            if var.type.name.upper() in type_map:
                kwargs[var.name] = (str | None,
                                    Field(description=f'{var.description} — provided as the string representation of a '
                                                      f'{var.type.name.upper()} variable', default=None))
            else:
                var_values = [v.value for v in var.type.values]
                default_value = [d for d in var_values if d.endswith('_OTHER')]
                if len(default_value) > 0:
                    default_value = default_value[0]
                else:
                    default_value = None
                kwargs[var.name] = (Literal[tuple(var_values)] | None,
                                    Field(description=var.description, default=default_value))
        return create_model('ProposalParameters', **kwargs)

    @classmethod
    def from_service_response(cls,
                              metadata: dict[str, str | int | datetime],
                              definition: dict[str, str | list[dict[str, str]]]):
        """Create Policy from Bedrock service get_automated_reasoning_policy response."""
        name = metadata['name']
        _id = metadata['policyId']
        description = metadata.get('description', '')
        definition_hash = metadata['definitionHash']
        version = metadata['version']
        arn = metadata['policyArn'] if version == 'DRAFT' else ':'.join(metadata['policyArn'].split(':')[:-1])

        # Parse policy definition
        custom_types = {t['name']: Type(**t) for t in definition.get('types', [])}
        builtin_types = {'INT': BaseType(name='INT', description='Integer number'),
                         'BOOL': BaseType(name='BOOL', description='Boolean value'),
                         'NUMBER': BaseType(name='NUMBER', description='Real number value')}
        types = custom_types | builtin_types

        variables = [Variable(name=var['name'], type=types[var['type']], description=var['description'])
                     for var in definition.get('variables', [])]

        rules = [Rule(id=rule['id'],
                      expression=rule['expression'],
                      alternate_expression=rule['alternateExpression'],
                      variables=[v for v in variables if v.name in rule['expression'].split()])
                 for rule in definition.get('rules', [])]

        return cls(name=name,
                   arn=arn,
                   id=_id,
                   description=description,
                   definition_hash=definition_hash,
                   version=version,
                   types=list(types.values()),
                   variables=variables,
                   rules=rules)

    @property
    def guardrail(self) -> Guardrail:
        """
        Create a Bedrock Guardrail that references this policy.

        Returns
        -------
        Guardrail object containing the guardrail details
        """
        if self._guardrail is not None:
            return self._guardrail

        bedrock_client = boto3.client('bedrock', region_name=config.region)

        # Determine regional inference profile based on region
        region_prefix = config.region.split('-')[0]
        region_map = {'us': 'us', 'eu': 'eu', 'ap': 'ap'}

        response = bedrock_client.create_guardrail(
            name=f'{uuid.uuid7().hex}',
            description=f'Guardrail for policy: {self.description}'[:200],
            automatedReasoningPolicyConfig={
                'policies': [self.versioned_arn],
                'confidenceThreshold': 1.0
            },
            crossRegionConfig={
                'guardrailProfileIdentifier': f"{region_map.get(region_prefix, 'US')}.guardrail.v1:0"
            },
            blockedInputMessaging=f'Policy {self.name} violated in input prompt',
            blockedOutputsMessaging=f'Policy {self.name} violated in response'
        )

        self._guardrail = Guardrail(
            id=response['guardrailId'],
            arn=response['guardrailArn'],
            version=response['version'],
            policy_arn=self.arn,
            confidence_threshold=1.0
        )

        return self._guardrail


class ResolvedVariable(Variable):
    """
    Represents a variable used in a rule definition with a resolved value
    """
    value: str | None = Field(default=None, description='Value of the variable')


class ResolvedRule(BaseModel):
    """
    Represents a formal policy rule with resolved variables.
    """
    id: str = Field(..., description="Unique identifier for the rule")
    expression: str = Field(..., min_length=1, description="The formal rule definition")
    alternate_expression: str = Field(..., min_length=1, description='Alternative version of the rule')
    variables: list[ResolvedVariable] = Field(..., description='List of variables that are part of this rule')


class ResolvedPolicy(Policy):
    """
    A formal policy with resolved rules
    """
    variables: list[ResolvedVariable]
    rules: list[ResolvedRule]
    proposal_paths: list[Path]
    comments: str | None = None
    ar_assessment: list[dict] | None = None
    _findings: Optional[list[ARCFinding]] = PrivateAttr(default=None)

    @property
    def findings(self) -> list[ARCFinding]:
        """Parse ar_assessment into structured findings after initialization."""
        if self.ar_assessment and not self._findings:
            self._findings = []
            for assessment in self.ar_assessment:
                try:
                    finding = ARCFinding(parent_policy=self, **assessment)
                    # Only add if there's actual content (not all None)
                    if finding.finding_type != "unknown":
                        self._findings.append(finding)
                except Exception as e:
                    logger.warning(f"Failed to parse finding: {e}")

        return self._findings

    @property
    def insights(self) -> str:
        """
        Extract insights from resolved policy findings.
        """
        if self.findings:
            insights = []
            for finding in self.findings:
                insights.append(finding.insight)
            return "\n\n".join(insights)
        elif self.comments:
            return self.comments

        return 'No insights available for this resolved policy'
