import os

from langchain_aws import ChatBedrockConverse
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.language_models import BaseChatModel

from client.messages import SYSTEM_PROMPT


LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID")

HAS_ANTHROPIC = os.environ.get("ANTHROPIC_API_KEY") is not None

HAS_BEDROCK = os.environ.get("AWS_BEARER_TOKEN_BEDROCK") is not None
BEDROCK_REGION = os.environ.get("AWS_REGION_BEDROCK", "us-west-2")

HAS_OPENAI = os.environ.get("OPENAI_API_KEY") is not None

current_model_name = None

def get_current_model_name():
    """Get the current model name."""
    return current_model_name

def get_llm_provider() -> BaseChatModel:
    """Get the LLM provider based on environment variable."""
    global current_model_name

    if LLM_PROVIDER == "anthropic":
        if not HAS_ANTHROPIC:
            raise ValueError("Selected Anthropic as provider but ANTHROPIC_API_KEY environment variable is not set.")
        current_model_name = LLM_MODEL_ID or "claude-3-5-sonnet-20241022"
        print(f"Creating Anthropic chat agent with model {current_model_name}")
        return ChatAnthropic(
            model=current_model_name,
            max_tokens=4096
        )
    if LLM_PROVIDER == "bedrock":
        if not HAS_BEDROCK:
            raise ValueError("Selected Bedrock as provider but AWS_BEARER_TOKEN_BEDROCK environment variable is not set.")
        current_model_name = LLM_MODEL_ID or "anthropic.claude-3-5-sonnet-20241022-v2:0"
        print(f"Creating Bedrock chat agent with model {current_model_name}")
        return ChatBedrockConverse(
            model_id=current_model_name,
            region_name=BEDROCK_REGION
        )
    if LLM_PROVIDER == "openai":
        if not HAS_OPENAI:
            raise ValueError("Selected OpenAI as provider but OPENAI_API_KEY environment variable is not set.")
        current_model_name = LLM_MODEL_ID or "gpt-5.3-codex"
        print(f"Creating OpenAI chat agent with model {current_model_name}")
        return ChatOpenAI(
            model=current_model_name,
            temperature=0
        )
    if LLM_PROVIDER == "ollama":
        current_model_name = LLM_MODEL_ID or "qwen2.5"
        print(f"Creating Ollama chat agent with model {current_model_name}")
        return ChatOllama(
            model=current_model_name, 
            system_prompt=SYSTEM_PROMPT
        )
    
    raise ValueError(f"Unsupported LLM provider: {LLM_PROVIDER}")