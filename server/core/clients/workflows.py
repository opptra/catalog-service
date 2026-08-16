"""Google Cloud Workflows client — one shared instance for the app lifetime."""

import json
from dataclasses import dataclass
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud.workflows import executions_v1
from google.cloud.workflows.executions_v1.types import Execution

from core.exceptions import WorkflowsError


@dataclass(frozen=True, slots=True)
class WorkflowExecution:
    """A started workflow execution (does not wait for completion)."""

    name: str
    workflow: str


class WorkflowsClient:
    """Trigger Cloud Workflows executions. Credentials come from ADC
    (``GOOGLE_APPLICATION_CREDENTIALS`` locally, the VM service account on GCE).
    """

    def __init__(self, project: str, location: str) -> None:
        if not project:
            raise ValueError("Google Cloud project is required")
        if not location:
            raise ValueError("Workflows location is required")
        self._project = project
        self._location = location
        self._executions = executions_v1.ExecutionsClient()

    def trigger(
        self,
        workflow: str,
        payload: dict[str, Any] | list[Any] | None = None,
    ) -> WorkflowExecution:
        """Start ``workflow`` with ``payload`` as the execution argument (JSON).

        ``workflow`` is the short workflow id (not the full resource name). Returns as soon
        as the execution is created — does not poll for completion.
        """
        if not workflow:
            raise ValueError("workflow is required")

        parent = (
            f"projects/{self._project}/locations/{self._location}/workflows/{workflow}"
        )
        argument = json.dumps(payload if payload is not None else {})
        try:
            execution = self._executions.create_execution(
                request={
                    "parent": parent,
                    "execution": Execution(argument=argument),
                }
            )
        except GoogleAPICallError as exc:
            raise WorkflowsError(
                f"Failed to trigger workflow {workflow!r}: {exc}"
            ) from exc

        return WorkflowExecution(name=execution.name, workflow=workflow)
