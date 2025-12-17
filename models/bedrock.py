import boto3
import logging
import botocore.exceptions
from pydantic import BaseModel
from misc.config import config

logger = logging.getLogger(__name__)


class Guardrail(BaseModel):
    """
    Container for Bedrock Guardrail details
    """
    id: str
    arn: str
    version: str
    policy_arn: str
    confidence_threshold: float

    def __del__(self):
        """
        Delete the guardrail automatically when the object is being deleted
        """
        logger.debug(f'Automatically cleaning up guardrail {self.id}')
        bedrock_client = boto3.client('bedrock', region_name=config.region)
        try:
            bedrock_client.delete_guardrail(guardrailIdentifier=self.id)
        except botocore.exceptions.ClientError as e:
            logging.warning(f'Error cleaning up Guardrail {self.id}, skipping')
            logging.exception(e)
