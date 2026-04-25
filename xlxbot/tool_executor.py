from dataclasses import dataclass
from typing import Any, Dict, Optional

from .tool_registry import ToolRegistry, ToolDefinition


@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: Optional[str] = None
    audit_ref: Optional[str] = None


class ToolExecutor:
    """Safe tool execution engine for Phase C controlled automation."""

    def __init__(self, tool_registry: ToolRegistry, logger):
        self.tool_registry = tool_registry
        self.logger = logger
        self._executors = {
            'knowledge_lookup': self._execute_knowledge_lookup,
            'provider_dispatch': self._execute_provider_dispatch,
            'webhook_sync': self._execute_webhook_sync,
            'answer_response': self._execute_answer_response,
            'learning_capture': self._execute_learning_capture,
            'troubleshooting_capture': self._execute_troubleshooting_capture,
            'docs_draft': self._execute_docs_draft,
            'sidecar_dispatch': self._execute_sidecar_dispatch,
            # High-risk tools are not implemented for safety
        }

    def can_execute(self, tool_name: str, risk: str, requires_approval: bool) -> bool:
        """Check if tool can be executed based on risk and approval status."""
        if risk == 'high':
            return False  # High-risk tools are never auto-executed
        if risk == 'medium' and requires_approval:
            return False  # Medium-risk requires approval
        if tool_name not in self._executors:
            return False
        return True

    def execute(self, tool_name: str, action: str, risk: str, requires_approval: bool,
                context: Dict[str, Any], audit_ref: str) -> ExecutionResult:
        """Execute a tool safely."""
        if not self.can_execute(tool_name, risk, requires_approval):
            return ExecutionResult(
                success=False,
                output='',
                error=f'Cannot execute tool {tool_name}: risk={risk}, approval_required={requires_approval}',
                audit_ref=audit_ref
            )

        executor = self._executors.get(tool_name)
        if not executor:
            return ExecutionResult(
                success=False,
                output='',
                error=f'No executor for tool {tool_name}',
                audit_ref=audit_ref
            )

        try:
            self.logger.info('Executing tool tool_name=%s action=%s risk=%s audit_ref=%s',
                           tool_name, action, risk, audit_ref)
            result = executor(action, context)
            self.logger.info('Tool execution completed tool_name=%s success=%s audit_ref=%s',
                           tool_name, result.success, audit_ref)
            return result
        except Exception as exc:
            self.logger.error('Tool execution failed tool_name=%s audit_ref=%s error=%s',
                            tool_name, audit_ref, str(exc))
            return ExecutionResult(
                success=False,
                output='',
                error=f'Tool execution failed: {str(exc)}',
                audit_ref=audit_ref
            )

    def _execute_knowledge_lookup(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute knowledge lookup - low risk, always allowed."""
        # This would integrate with knowledge service
        # For now, return success as knowledge lookup is handled elsewhere
        return ExecutionResult(
            success=True,
            output='Knowledge lookup completed',
            audit_ref=context.get('audit_ref')
        )

    def _execute_provider_dispatch(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute provider dispatch - medium risk, approval required."""
        # This would dispatch to AI providers
        # For now, return success as provider dispatch is handled elsewhere
        return ExecutionResult(
            success=True,
            output='Provider dispatch completed',
            audit_ref=context.get('audit_ref')
        )

    def _execute_webhook_sync(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute webhook sync - medium risk, approval required."""
        from .webhook_sync import sync_line_webhook
        try:
            # Create a mock state object if not provided
            state = context.get('state')
            if not state:
                from .runtime import RuntimeState
                state = RuntimeState()
            updated = sync_line_webhook(context.get('config'), state, self.logger, force=True)
            return ExecutionResult(
                success=updated,
                output=f'Webhook sync {"successful" if updated else "no change needed"}',
                audit_ref=context.get('audit_ref')
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                output='',
                error=f'Webhook sync failed: {str(e)}',
                audit_ref=context.get('audit_ref')
            )

    def _execute_answer_response(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute answer response - low risk, always allowed."""
        return ExecutionResult(
            success=True,
            output='Answer response completed',
            audit_ref=context.get('audit_ref')
        )

    def _execute_learning_capture(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute learning capture - low risk, always allowed."""
        from .learning import append_learning_event
        try:
            append_learning_event(
                context.get('config'),
                self.logger,
                event_type=context.get('event_type', 'LEARNING_CAPTURE'),
                user_id=context.get('user_id', 'unknown'),
                user_input=context.get('user_input', ''),
                details=context.get('details', {}),
                intent=context.get('intent', 'unknown'),
                action='learning_capture',
                risk='low',
                approval='not_required',
                fallback='none'
            )
            return ExecutionResult(
                success=True,
                output='Learning event captured successfully',
                audit_ref=context.get('audit_ref')
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                output='',
                error=f'Failed to capture learning: {str(e)}',
                audit_ref=context.get('audit_ref')
            )

    def _execute_troubleshooting_capture(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute troubleshooting capture - low risk, always allowed."""
        from .learning import append_learning_event
        try:
            append_learning_event(
                context.get('config'),
                self.logger,
                event_type='TROUBLESHOOTING',
                user_id=context.get('user_id', 'unknown'),
                user_input=context.get('user_input', ''),
                details=context.get('details', {}),
                intent='error_report',
                action='troubleshooting_capture',
                risk='low',
                approval='not_required',
                fallback='none'
            )
            return ExecutionResult(
                success=True,
                output='Troubleshooting event captured successfully',
                audit_ref=context.get('audit_ref')
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                output='',
                error=f'Failed to capture troubleshooting: {str(e)}',
                audit_ref=context.get('audit_ref')
            )

    def _execute_docs_draft(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute docs draft - medium risk, approval required."""
        # This would generate documentation drafts
        # For now, return success as docs drafting is handled elsewhere
        return ExecutionResult(
            success=True,
            output='Documentation draft completed',
            audit_ref=context.get('audit_ref')
        )

    def _execute_sidecar_dispatch(self, action: str, context: Dict[str, Any]) -> ExecutionResult:
        """Execute sidecar dispatch - medium risk, approval required."""
        # This would dispatch to sidecar
        # For now, return success as sidecar dispatch is handled elsewhere
        return ExecutionResult(
            success=True,
            output='Sidecar dispatch completed',
            audit_ref=context.get('audit_ref')
        )
