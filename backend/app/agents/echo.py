"""Agente «eco»: valida la infraestructura (salida tipada, reintentos, límites) sin LLM real."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent

from app.agents.prompts import ECHO_PROMPT


class EchoReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str
    length: int = Field(ge=0)


# Sin modelo: debe inyectarse con `Agent.override` o el argumento `model` (D84).
# Máximo 2 reintentos de validación de salida (D85).
echo_agent: Agent[None, EchoReport] = Agent(
    output_type=EchoReport,
    system_prompt=ECHO_PROMPT,
    retries=2,
    name="echo",
)
