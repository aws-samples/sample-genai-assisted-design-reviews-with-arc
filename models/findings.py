"""Pydantic models for Bedrock Automated Reasoning assessment findings."""

from pydantic import BaseModel, Field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from models.arc import ResolvedPolicy


class GuardrailAutomatedReasoningRule(BaseModel):
    """Represents a policy rule in automated reasoning."""
    model_config = {"extra": "allow"}


class GuardrailAutomatedReasoningLogicWarning(BaseModel):
    """Indication of a logic issue with the translation."""
    model_config = {"extra": "allow"}


class GuardrailAutomatedReasoningTranslation(BaseModel):
    """Logical translation of natural language input."""
    model_config = {"extra": "allow"}


class GuardrailAutomatedReasoningScenario(BaseModel):
    """Scenario demonstrating logical outcomes."""
    model_config = {"extra": "allow"}


class GuardrailAutomatedReasoningTranslationOption(BaseModel):
    """One possible logical interpretation of ambiguous input."""
    examples: list[GuardrailAutomatedReasoningTranslation] | None = None


class ImpossibleFinding(BaseModel):
    """No valid claims can be made due to logical contradictions."""
    contradicting_rules: list[GuardrailAutomatedReasoningRule] | None = Field(None, alias="contradictingRules")
    logic_warning: GuardrailAutomatedReasoningLogicWarning | None = Field(None, alias="logicWarning")
    translation: GuardrailAutomatedReasoningTranslation | None = None
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        return "❌ **Impossible**: No valid logical conclusions can be drawn due to contradictions in the premises or policy rules."


class InvalidFinding(BaseModel):
    """Claims are logically false and contradict established rules."""
    contradicting_rules: list[GuardrailAutomatedReasoningRule] | None = Field(None, alias="contradictingRules")
    logic_warning: GuardrailAutomatedReasoningLogicWarning | None = Field(None, alias="logicWarning")
    translation: GuardrailAutomatedReasoningTranslation | None = None
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        if self.contradicting_rules:
            msg = ''
            for contradicting_rule in self.contradicting_rules:
                rule = [r for r in self._parent_policy.rules
                        if r.id == contradicting_rule.identifier][0]
                msg += f'- **{rule.id}**: {rule.alternate_expression}\n'
                msg += '\n'.join(
                    [f'    + **{r.name}**: {"**" + r.value + "**" if r.value else "*Unknown*"} ({r.description})'
                     for r in rule.variables if r.name != 'IsCompliantWithFullPolicy'])
            plural = 's' if len(self.contradicting_rules) > 1 else ''
            return f"❌ **Non-Compliant**: The proposal appears to violate the following rule{plural}:\n\n{msg}"
        return "❌ **Non-Compliant**: The proposal does not satisfy the policy requirements."


class NoTranslationsFinding(BaseModel):
    """No relevant logical information could be extracted."""
    model_config = {"extra": "allow"}
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        return "⚠️ **No Translation**: Cannot extract relevant logical information from the input for validation."


class SatisfiableFinding(BaseModel):
    """Claims could be true or false depending on additional assumptions."""
    claims_false_scenario: GuardrailAutomatedReasoningScenario | None = Field(None, alias="claimsFalseScenario")
    claims_true_scenario: GuardrailAutomatedReasoningScenario | None = Field(None, alias="claimsTrueScenario")
    logic_warning: GuardrailAutomatedReasoningLogicWarning | None = Field(None, alias="logicWarning")
    translation: GuardrailAutomatedReasoningTranslation | None = None
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        return ("⚠️ **Satisfiable**: The policy might be compliant, but additional information is needed. "
                "Some variables or assumptions are missing to make a complete assessment.")


class TooComplexFinding(BaseModel):
    """Input exceeds processing capacity due to volume or complexity."""
    model_config = {"extra": "allow"}
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        return ("❌ **Too Complex**: Cannot evaluate the policies because the input is too complex "
                "(typically there are too many variables).")


class TranslationAmbiguousFinding(BaseModel):
    """Input has multiple valid logical interpretations."""
    difference_scenarios: list[GuardrailAutomatedReasoningScenario] | None = Field(None, alias="differenceScenarios")
    options: list[GuardrailAutomatedReasoningTranslationOption] | None = None
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        if self.options:
            option_count = len(self.options)
            return (f"⚠️ **Ambiguous**: The input has {option_count} valid logical interpretations. "
                    "Additional context or clarification is required (e.g., date formats, units, terminology).")
        return "⚠️ **Ambiguous**: The input has multiple valid interpretations requiring clarification."


class ValidFinding(BaseModel):
    """Claims are definitively true and logically implied by premises."""
    claims_true_scenario: GuardrailAutomatedReasoningScenario | None = Field(None, alias="claimsTrueScenario")
    logic_warning: GuardrailAutomatedReasoningLogicWarning | None = Field(None, alias="logicWarning")
    supporting_rules: list[GuardrailAutomatedReasoningRule] | None = Field(None, alias="supportingRules")
    translation: GuardrailAutomatedReasoningTranslation | None = None
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        if self.supporting_rules:
            rule_count = len(self.supporting_rules)
            return f"✅ **Compliant**: The proposal satisfies this policy. Validated against {rule_count} rule(s)."
        return ("✅ **Compliant**: The proposal satisfies this policy as interpreted, please review the variable "
                "assignments to ensure that they have been understood properly.")


class NotApplicableFinding(BaseModel):
    """Policy does not apply to this proposal (no variables resolved)."""
    model_config = {"extra": "allow"}
    _parent_policy: Any = None

    @property
    def insight(self) -> str:
        return "ℹ️ **Not Applicable**: Could not extract any findings related to the policy. Maybe it does not apply?"


class ARCFinding(BaseModel):
    """Union type for all possible ARc assessment findings."""
    not_applicable: NotApplicableFinding | None = Field(None, alias="notApplicable")
    impossible: ImpossibleFinding | None = None
    invalid: InvalidFinding | None = None
    no_translations: NoTranslationsFinding | None = Field(None, alias="noTranslations")
    satisfiable: SatisfiableFinding | None = None
    too_complex: TooComplexFinding | None = Field(None, alias="tooComplex")
    translation_ambiguous: TranslationAmbiguousFinding | None = Field(None, alias="translationAmbiguous")
    valid: ValidFinding | None = None
    parent_policy: Any = Field(None, exclude=True)

    def model_post_init(self, __context):
        """Propagate parent policy reference to child findings."""
        if self.parent_policy:
            for finding in [self.not_applicable, self.impossible, self.invalid, self.no_translations,
                            self.satisfiable, self.too_complex, self.translation_ambiguous, self.valid]:
                if finding:
                    finding._parent_policy = self.parent_policy

    @property
    def finding_type(self) -> str:
        """Return the type of finding present."""
        if self.not_applicable:
            return "not_applicable"
        elif self.impossible:
            return "impossible"
        elif self.invalid:
            return "invalid"
        elif self.no_translations:
            return "no_translations"
        elif self.satisfiable:
            return "satisfiable"
        elif self.too_complex:
            return "too_complex"
        elif self.translation_ambiguous:
            return "translation_ambiguous"
        elif self.valid:
            return "valid"
        return "unknown"

    @property
    def severity(self) -> str:
        """Return severity level: success, warning, or error."""
        if self.valid:
            return "success"
        elif self.not_applicable or self.satisfiable or self.translation_ambiguous or self.no_translations:
            return "warning"
        else:  # impossible, invalid, too_complex
            return "error"

    @property
    def insight(self) -> str:
        """Get human-readable insight for this finding."""
        if self.not_applicable:
            return self.not_applicable.insight
        elif self.impossible:
            return self.impossible.insight
        elif self.invalid:
            return self.invalid.insight
        elif self.no_translations:
            return self.no_translations.insight
        elif self.satisfiable:
            return self.satisfiable.insight
        elif self.too_complex:
            return self.too_complex.insight
        elif self.translation_ambiguous:
            return self.translation_ambiguous.insight
        elif self.valid:
            return self.valid.insight
        return "No finding available"
