"""
MCP Client - Single MCP server connection wrapper.

Based on better-chatbot's create-mcp-client.ts pattern.
Uses Python MCP SDK (@modelcontextprotocol/sdk Python equivalent).
"""

from typing import Any, Dict, List, Optional
import asyncio
import subprocess
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class MCPClientStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPToolInfo:
    """Tool information from MCP server."""
    name: str
    description: str
    input_schema: Dict[str, Any]


@dataclass
class MCPServerConfig:
    """MCP server configuration."""
    # For stdio transport
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    
    # For HTTP/SSE transport
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    def is_stdio(self) -> bool:
        return self.command is not None
    
    def is_remote(self) -> bool:
        return self.url is not None


class MCPClient:
    """
    Client class for Model Context Protocol (MCP) server connections.
    
    Equivalent to better-chatbot's MCPClient class.
    """
    
    def __init__(
        self, 
        id: str, 
        name: str, 
        config: MCPServerConfig,
        auto_disconnect_seconds: Optional[int] = None
    ):
        self.id = id
        self.name = name
        self.config = config
        self.auto_disconnect_seconds = auto_disconnect_seconds
        
        self._client = None
        self._transport = None
        self._status = MCPClientStatus.DISCONNECTED
        self._error: Optional[str] = None
        self._tool_info: List[MCPToolInfo] = []
        self._lock = asyncio.Lock()
        self.exit_stack = None
    
    @property
    def status(self) -> MCPClientStatus:
        return self._status
    
    @property
    def tool_info(self) -> List[MCPToolInfo]:
        return self._tool_info
    
    @property
    def error(self) -> Optional[str]:
        return self._error
    
    def get_info(self) -> Dict[str, Any]:
        """Get server info for API response."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self._status.value,
            "error": self._error,
            "tool_info": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema
                }
                for t in self._tool_info
            ]
        }
    
    async def connect(self) -> bool:
        """Connect to MCP server."""
        async with self._lock:
            if self._status == MCPClientStatus.CONNECTED:
                return True
            
            self._status = MCPClientStatus.CONNECTING
            self._error = None
            
            try:
                if self.config.is_stdio():
                    await self._connect_stdio()
                elif self.config.is_remote():
                    await self._connect_remote()
                else:
                    raise ValueError("Invalid server config: must have command or url")
                
                self._status = MCPClientStatus.CONNECTED
                await self._update_tool_info()
                logger.info(f"[{self.name}] Connected to MCP server")
                return True
                
            except Exception as e:
                self._status = MCPClientStatus.ERROR
                self._error = str(e)
                logger.error(f"[{self.name}] Failed to connect: {e}")
                return False
    
    async def _connect_stdio(self):
        """Connect using stdio transport (subprocess)."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from contextlib import AsyncExitStack
            
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args or [],
                env=self.config.env,
            )
            
            self.exit_stack = AsyncExitStack()
            
            self._transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            read, write = self._transport
            self._client = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await self._client.initialize()
            
        except ImportError:
            # Fallback if mcp package not installed - use subprocess directly
            logger.warning("mcp package not installed, using mock connection")
            self._client = MockMCPClient(self.config)
            await self._client.initialize()
    
    async def _connect_remote(self):
        """Connect using HTTP/SSE transport."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
            from contextlib import AsyncExitStack
            
            self.exit_stack = AsyncExitStack()
            
            self._transport = await self.exit_stack.enter_async_context(
                sse_client(self.config.url, headers=self.config.headers)
            )
            read, write = self._transport
            self._client = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await self._client.initialize()
            
        except ImportError:
            logger.warning("mcp package not installed, using mock connection")
            self._client = MockMCPClient(self.config)
            await self._client.initialize()
    
    async def _update_tool_info(self):
        """Fetch tool information from MCP server."""
        if self._client is None:
            return
        
        try:
            tools_result = await self._client.list_tools()
            self._tool_info = [
                MCPToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or {"type": "object", "properties": {}}
                )
                for tool in tools_result.tools
            ]
            logger.info(f"[{self.name}] Found {len(self._tool_info)} tools")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to list tools: {e}")
            self._tool_info = []
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> Any:
        """Call a tool on the MCP server."""
        if self._status != MCPClientStatus.CONNECTED:
            await self.connect()
        
        if self._client is None:
            raise RuntimeError(f"Not connected to MCP server: {self.name}")
        
        try:
            logger.info(f"[{self.name}] Calling tool: {tool_name}")
            result = await self._client.call_tool(tool_name, arguments or {})
            return self._parse_tool_result(result)
        except Exception as e:
            logger.error(f"[{self.name}] Tool call failed: {e}")
            return {
                "isError": True,
                "error": {"name": "ToolCallError", "message": str(e)},
                "content": []
            }
    
    def _parse_tool_result(self, result) -> Dict[str, Any]:
        """Parse MCP tool result to standard format."""
        if hasattr(result, 'content'):
            content = []
            for item in result.content:
                if hasattr(item, 'text'):
                    content.append({"type": "text", "text": item.text})
                else:
                    content.append({"type": "unknown", "data": str(item)})
            return {
                "isError": getattr(result, 'isError', False),
                "content": content
            }
        return {"content": [{"type": "text", "text": str(result)}]}
    
    async def disconnect(self):
        """Disconnect from MCP server."""
        async with self._lock:
            if hasattr(self, 'exit_stack') and self.exit_stack:
                try:
                    await self.exit_stack.aclose()
                except Exception as e:
                    logger.warning(f"[{self.name}] Error during disconnect: {e}")
                finally:
                    self.exit_stack = None
            
            self._client = None
            self._transport = None
            
            self._status = MCPClientStatus.DISCONNECTED
            logger.info(f"[{self.name}] Disconnected from MCP server")


class MockMCPClient:
    """Mock MCP client for when mcp package is not installed."""
    
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.tools = []
    
    async def initialize(self):
        """Mock initialization."""
        pass
    
    async def list_tools(self):
        """Return empty tool list."""
        class MockResult:
            tools = []
        return MockResult()
    
    async def call_tool(self, name: str, arguments: dict):
        """Mock tool call."""
        class MockContent:
            text = f"Mock response for tool: {name}"
        class MockResult:
            content = [MockContent()]
            isError = False
        return MockResult()
