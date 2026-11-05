"""Explicit, lazily constructed application dependencies with per-app isolation."""
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable

@dataclass
class RuntimeServices:
    service: object
    plans: object
    agent: object
    images: object
    contact: object
    scheduler: object


def build_services(root=None):
    from app.mcd import McdService
    from app.plans import PlanStore
    from app.agent import AgentService
    from app.attachments import ImageStore
    from app.contact import ContactService
    from app.foundation_scheduler import FoundationScheduler
    production=root is None
    root=Path(root or Path(__file__).resolve().parents[1]/'.local-data')
    service=McdService()
    plans=PlanStore(root/'plans.sqlite3',recover_running=False)
    agent=AgentService(service,plans,data_dir=None if production else root/'personal-agent')
    images=ImageStore(agent.data_dir/'images')
    contact=ContactService(agent,agent.data_dir/'contact.sqlite3',images=images)
    scheduler=FoundationScheduler(agent.data_dir/'scheduler')
    return RuntimeServices(service,plans,agent,images,contact,scheduler)


class RuntimeSlot:
    def __init__(self,services=None,factory:Callable=build_services):
        self._services=services
        self.factory=factory
        self._lock=RLock()

    def get(self):
        with self._lock:
            if self._services is None:self._services=self.factory()
            return self._services

current_runtime=ContextVar('xiaorui_runtime',default=None)
default_runtime=RuntimeSlot()


class ServiceProxy:
    """Compatibility for old imports; contains no database, network or lifecycle.

    Request handlers resolve the current app's injected dependencies. Tests and
    older integrations may still patch a named dependency during migration.
    """
    def __init__(self,name):
        object.__setattr__(self,'_name',name)

    def _target(self):
        return getattr((current_runtime.get() or default_runtime).get(),self._name)

    def __getattr__(self,name):
        return getattr(self._target(),name)

    def __setattr__(self,name,value):
        setattr(self._target(),name,value)
