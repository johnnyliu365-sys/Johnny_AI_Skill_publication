"""Adapters for public Agents SDK and MCP resource interfaces."""

from __future__ import annotations

from agents import Agent
from mcp import ClientSession
from mcp.types import TextResourceContents
from pydantic import AnyUrl

from .contracts import ArtifactRef, CapabilityRef, NonBlankText, RouterModel, SourceSnippet


class AgentCapabilityDefinition(RouterModel):
    """The local configuration that binds one CapabilityRef to an Agents SDK Agent."""

    capability: CapabilityRef
    agent_name: NonBlankText
    instructions: NonBlankText
    model: str | None = None


class OpenAICapabilityAdapter:
    """Resolve only router-approved capability definitions into SDK Agent instances."""

    def __init__(self, *, definitions: tuple[AgentCapabilityDefinition, ...]) -> None:
        self._definitions = definitions

    def resolve(self, *, capability: CapabilityRef) -> Agent[None]:
        """Build an Agent definition without running a model or granting extra handoffs."""

        for definition in self._definitions:
            if definition.capability == capability:
                return Agent(
                    name=definition.agent_name,
                    instructions=definition.instructions,
                    model=definition.model,
                )
        raise ValueError(f"capability is not registered: {capability.capability_id}")


class McpResourceGateway:
    """Read one explicitly allowed MCP resource and normalize it into a typed source snippet."""

    def __init__(self, *, session: ClientSession) -> None:
        self._session = session

    async def read(self, *, source: ArtifactRef, span: str) -> SourceSnippet:
        """Fail closed unless the MCP server returns exactly one text resource."""

        result = await self._session.read_resource(AnyUrl(source.uri))
        contents = tuple(
            content for content in result.contents if isinstance(content, TextResourceContents)
        )
        if len(contents) != 1:
            raise ValueError("MCP source must resolve to exactly one text resource")
        return SourceSnippet(source=source, span=span, text=contents[0].text)
