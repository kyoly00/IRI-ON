"""
MCP Clients Manager - Manages multiple MCP server connections.

Based on better-chatbot's create-mcp-clients-manager.ts pattern.
Provides a singleton manager for connecting to MCP servers and calling tools.
"""

from typing import Any, Dict, List, Optional
import asyncio
import json
import logging
from pathlib import Path
from dataclasses import dataclass

from services.mcp_client import MCPClient, MCPServerConfig, MCPToolInfo

logger = logging.getLogger(__name__)


def create_mcp_tool_id(server_name: str, tool_name: str) -> str:
    """Create unique tool ID combining server and tool names."""
    return f"{server_name}:{tool_name}"


def parse_mcp_tool_id(tool_id: str) -> tuple[str, str]:
    """Parse tool ID back to server_name and tool_name."""
    if ":" in tool_id:
        server_name, tool_name = tool_id.split(":", 1)
        return server_name, tool_name
    return "", tool_id


@dataclass
class MCPToolDefinition:
    """Tool definition for OpenAI Realtime binding."""
    name: str
    type: str = "function"
    description: str = ""
    parameters: Dict[str, Any] = None
    
    # Internal metadata
    _server_id: str = ""
    _server_name: str = ""
    _origin_tool_name: str = ""
    
    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format for session binding."""
        return {
            "type": self.type,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {
                "type": "object",
                "properties": {},
                "required": []
            }
        }


class MCPClientsManager:
    """
    Manager for multiple MCP client connections.
    
    Equivalent to better-chatbot's MCPClientsManager class.
    """
    
    def __init__(self, auto_disconnect_seconds: int = 1800):  # 30 minutes
        self._clients: Dict[str, MCPClient] = {}
        self._auto_disconnect_seconds = auto_disconnect_seconds
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._config_path: Optional[Path] = None
    
    async def init(self, config_path: Optional[Path] = None):
        """Initialize manager with MCP server configs."""
        async with self._init_lock:
            if self._initialized:
                return
            
            # Load config from mcp-tools.config.json
            if config_path:
                self._config_path = config_path
            else:
                # Default path relative to be/ directory
                self._config_path = (
                    Path(__file__).parents[2] / 
                    "fe/app/src/lib/ai/speech/open-ai/mcp-tools.config.json"
                )
            
            if self._config_path.exists():
                await self._load_config()
            else:
                logger.warning(f"MCP config not found: {self._config_path}")
            
            self._initialized = True
            logger.info(f"MCPClientsManager initialized with {len(self._clients)} servers")
    
    async def _load_config(self):
        """Load MCP server configurations from config file."""
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            mcp_servers = config.get("mcpServers", {})
            
            for server_name, server_config in mcp_servers.items():
                await self.add_client(
                    id=server_name,
                    name=server_name,
                    config=self._parse_server_config(server_config)
                )
                
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}")
    
    def _parse_server_config(self, config: Dict[str, Any]) -> MCPServerConfig:
        """Parse server config dict to MCPServerConfig."""
        if "command" in config:
            # Stdio transport
            command = config.get("command", "")
            args = config.get("args", [])
            
            # Handle npx command with inline arguments
            if isinstance(command, str) and command.startswith("npx "):
                parts = command.split()
                command = parts[0]
                args = parts[1:] + args
            
            return MCPServerConfig(
                command=command,
                args=args,
                env=config.get("env")
            )
        elif "url" in config:
            # HTTP transport
            return MCPServerConfig(
                url=config.get("url"),
                headers=config.get("headers")
            )
        else:
            raise ValueError(f"Invalid server config: {config}")
    
    async def add_client(
        self, 
        id: str, 
        name: str, 
        config: MCPServerConfig
    ) -> MCPClient:
        """Add a new MCP client."""
        client = MCPClient(
            id=id,
            name=name,
            config=config,
            auto_disconnect_seconds=self._auto_disconnect_seconds
        )
        self._clients[id] = client
        logger.info(f"Added MCP client: {name}")
        return client
    
    async def remove_client(self, id: str):
        """Remove and disconnect an MCP client."""
        if id in self._clients:
            await self._clients[id].disconnect()
            del self._clients[id]
            logger.info(f"Removed MCP client: {id}")
    
    def get_client(self, id: str) -> Optional[MCPClient]:
        """Get an MCP client by ID."""
        return self._clients.get(id)
    
    def get_clients(self) -> List[Dict[str, Any]]:
        """Get all clients info."""
        return [
            {"id": id, "client": client}
            for id, client in self._clients.items()
        ]
    
    async def tools(self) -> List[MCPToolDefinition]:
        """
        Return all tools from all connected MCP servers.
        
        Equivalent to better-chatbot's MCPClientsManager.tools() method.
        """
        all_tools: List[MCPToolDefinition] = []
        
        for server_id, client in self._clients.items():
            # Ensure connected
            if client.status.value != "connected":
                connected = await client.connect()
                if not connected:
                    logger.warning(f"Failed to connect to {server_id}, skipping tools")
                    continue
            
            for tool_info in client.tool_info:
                tool_id = create_mcp_tool_id(client.name, tool_info.name)
                
                tool_def = MCPToolDefinition(
                    name=tool_id,
                    description=tool_info.description,
                    parameters=tool_info.input_schema,
                    _server_id=server_id,
                    _server_name=client.name,
                    _origin_tool_name=tool_info.name
                )
                all_tools.append(tool_def)
        
        return all_tools
    
    async def tools_for_openai(self) -> List[Dict[str, Any]]:
        """Get tools formatted for OpenAI Realtime session binding."""
        tools = await self.tools()
        return [tool.to_openai_format() for tool in tools]
    
    async def tool_call(
        self, 
        server_id: str, 
        tool_name: str, 
        arguments: Dict[str, Any]
    ) -> Any:
        """
        Call a tool on a specific MCP server.
        
        Equivalent to better-chatbot's MCPClientsManager.toolCall() method.
        """
        client = self._clients.get(server_id)
        if not client:
            return {
                "isError": True,
                "error": {"name": "ClientNotFound", "message": f"MCP client not found: {server_id}"},
                "content": []
            }
        
        return await client.call_tool(tool_name, arguments)
    
    async def tool_call_by_tool_id(
        self, 
        tool_id: str, 
        arguments: Dict[str, Any]
    ) -> Any:
        """
        Call a tool using the combined tool_id (server_name:tool_name).
        
        This is the main method called from the frontend bridge.
        """
        server_name, tool_name = parse_mcp_tool_id(tool_id)
        
        # Find client by name
        for client in self._clients.values():
            if client.name == server_name:
                return await client.call_tool(tool_name, arguments)
        
        return {
            "isError": True,
            "error": {"name": "ClientNotFound", "message": f"MCP server not found: {server_name}"},
            "content": []
        }
    
    async def cleanup(self):
        """Disconnect all clients."""
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()
        self._initialized = False


# Global singleton instance
_mcp_manager: Optional[MCPClientsManager] = None


async def get_mcp_manager() -> MCPClientsManager:
    """Get the global MCP clients manager instance."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPClientsManager()
        await _mcp_manager.init()
    return _mcp_manager


async def init_mcp_manager(config_path: Optional[Path] = None) -> MCPClientsManager:
    """Initialize the global MCP clients manager."""
    global _mcp_manager
    _mcp_manager = MCPClientsManager()
    await _mcp_manager.init(config_path)
    return _mcp_manager
