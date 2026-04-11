"""
AXIOM Backend — Agent Manager

Orchestrates the lifecycle of autonomous demo agents.
Tracks active agent instances in memory.
"""

import logging
from typing import Dict, List, Optional
from axiom_agpp.demo_agent import GroqAgent

logger = logging.getLogger(__name__)

class AgentManager:
    _instance = None
    _agents: Dict[str, GroqAgent] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentManager, cls).__new__(cls)
        return cls._instance

    def spawn_agent(
        self,
        name: str,
        role: str,
        task: str,
        api_key: Optional[str] = None
    ) -> GroqAgent:
        """
        Create and track a new GroqAgent.
        """
        if name in self._agents:
            logger.warning(f"Agent with name {name} already exists. Re-initializing.")
        
        agent = GroqAgent(
            name=name,
            role=role,
            task_goal=task,
            api_key=api_key,
            mock_mode=not api_key
        )
        
        # Bootstrap the agent's on-chain presence (funding + contract init)
        try:
            agent.wrapper.bootstrap()
            logger.info(f"Agent {name} bootstrapped on-chain")
        except Exception as e:
            logger.error(f"Failed to bootstrap agent {name}: {e}")
            raise Exception(f"Failed to fund agent on Testnet! Please use the Algorand testnet bank to fund your Deployer address. Error: {e}")

        self._agents[name] = agent
        logger.info(f"Agent spawned: {name} ({agent.address[:10]}...)")
        return agent

    def get_agent(self, name: str) -> Optional[GroqAgent]:
        return self._agents.get(name)

    def list_agents(self) -> List[dict]:
        return [agent.to_dict() for agent in self._agents.values()]

    def kill_agent(self, name: str) -> bool:
        if name in self._agents:
            del self._agents[name]
            return True
        return False

# Global singleton
manager = AgentManager()
