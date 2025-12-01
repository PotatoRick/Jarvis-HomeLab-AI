"""
Runbook manager for structured remediation guidance.

Phase 4: Loads runbooks from markdown files to provide Claude
with structured remediation steps for specific alert types.
"""

import os
import re
import glob
import structlog
from typing import Optional, Dict, List
from pathlib import Path
from dataclasses import dataclass

logger = structlog.get_logger()


@dataclass
class Runbook:
    """Structured runbook data."""
    alert_name: str
    title: str
    overview: str
    investigation_steps: List[str]
    common_causes: List[str]
    remediation_steps: List[str]
    commands: List[str]
    risk_level: str
    estimated_duration: str
    raw_content: str


class RunbookManager:
    """Load and manage runbooks for remediation guidance."""

    def __init__(self, runbook_dir: str = "/app/runbooks"):
        """
        Initialize runbook manager.

        Args:
            runbook_dir: Directory containing runbook markdown files
        """
        self.runbook_dir = Path(runbook_dir)
        self.runbooks: Dict[str, Runbook] = {}
        self.logger = logger.bind(component="runbook_manager")

    def load_runbooks(self) -> int:
        """
        Load all runbook markdown files from the runbook directory.

        Returns:
            Number of runbooks loaded
        """
        if not self.runbook_dir.exists():
            self.logger.warning(
                "runbook_directory_not_found",
                path=str(self.runbook_dir)
            )
            return 0

        loaded = 0
        for filepath in self.runbook_dir.glob("*.md"):
            try:
                runbook = self._parse_runbook(filepath)
                if runbook:
                    self.runbooks[runbook.alert_name.lower()] = runbook
                    loaded += 1
                    self.logger.debug(
                        "runbook_loaded",
                        alert_name=runbook.alert_name,
                        file=filepath.name
                    )
            except Exception as e:
                self.logger.error(
                    "runbook_parse_failed",
                    file=filepath.name,
                    error=str(e)
                )

        self.logger.info(
            "runbooks_loaded",
            count=loaded,
            directory=str(self.runbook_dir)
        )

        return loaded

    def _parse_runbook(self, filepath: Path) -> Optional[Runbook]:
        """
        Parse a runbook markdown file into structured data.

        Args:
            filepath: Path to markdown file

        Returns:
            Runbook object or None if parsing fails
        """
        content = filepath.read_text()

        # Extract alert name from filename or h1 header
        alert_name = filepath.stem  # Filename without extension

        # Try to get title from first h1
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else f"{alert_name} Runbook"

        # Extract sections
        overview = self._extract_section(content, "Overview", "Investigation")
        investigation = self._extract_list_section(content, "Investigation")
        causes = self._extract_list_section(content, "Common Causes")
        remediation = self._extract_list_section(content, "Remediation")
        commands = self._extract_code_blocks(content)

        # Extract metadata from frontmatter if present
        risk_level = self._extract_metadata(content, "risk_level", "medium")
        estimated_duration = self._extract_metadata(content, "estimated_duration", "5-10 minutes")

        return Runbook(
            alert_name=alert_name,
            title=title,
            overview=overview,
            investigation_steps=investigation,
            common_causes=causes,
            remediation_steps=remediation,
            commands=commands,
            risk_level=risk_level,
            estimated_duration=estimated_duration,
            raw_content=content
        )

    def _extract_section(
        self,
        content: str,
        section_name: str,
        next_section: str = None
    ) -> str:
        """Extract content between section headers."""
        pattern = rf'##\s+{section_name}.*?\n(.*?)'
        if next_section:
            pattern += rf'(?=##\s+{next_section}|$)'
        else:
            pattern += r'(?=##|$)'

        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_list_section(self, content: str, section_name: str) -> List[str]:
        """Extract bullet points from a section."""
        section = self._extract_section(content, section_name)
        if not section:
            return []

        # Match numbered or bullet list items
        items = re.findall(r'^\s*[\d\.\-\*]+\s*(.+)$', section, re.MULTILINE)
        return [item.strip() for item in items if item.strip()]

    def _extract_code_blocks(self, content: str) -> List[str]:
        """Extract all code blocks (bash commands)."""
        # Match fenced code blocks
        pattern = r'```(?:bash|sh)?\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)

        commands = []
        for block in matches:
            # Split into individual commands
            for line in block.strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    commands.append(line)

        return commands

    def _extract_metadata(self, content: str, key: str, default: str) -> str:
        """Extract metadata from YAML frontmatter or inline comments."""
        # Check YAML frontmatter
        frontmatter_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if frontmatter_match:
            fm_content = frontmatter_match.group(1)
            key_match = re.search(rf'^{key}:\s*(.+)$', fm_content, re.MULTILINE)
            if key_match:
                return key_match.group(1).strip().strip('"\'')

        # Check inline comments
        inline_match = re.search(rf'<!--\s*{key}:\s*(.+?)\s*-->', content)
        if inline_match:
            return inline_match.group(1).strip()

        return default

    def get_runbook(self, alert_name: str) -> Optional[Runbook]:
        """
        Get runbook for an alert type.

        Args:
            alert_name: Name of the alert (case-insensitive)

        Returns:
            Runbook or None if not found
        """
        # Exact match
        key = alert_name.lower()
        if key in self.runbooks:
            return self.runbooks[key]

        # Partial match (alert name contains runbook name or vice versa)
        for runbook_key, runbook in self.runbooks.items():
            if runbook_key in key or key in runbook_key:
                return runbook

        return None

    def get_runbook_context(self, alert_name: str) -> str:
        """
        Get formatted runbook content for Claude context.

        Args:
            alert_name: Name of the alert

        Returns:
            Formatted string for system prompt, or empty string if no runbook
        """
        runbook = self.get_runbook(alert_name)
        if not runbook:
            return ""

        context = f"""
## Runbook: {runbook.title}

### Overview
{runbook.overview}

### Investigation Steps
{self._format_list(runbook.investigation_steps)}

### Common Causes
{self._format_list(runbook.common_causes)}

### Remediation Steps
{self._format_list(runbook.remediation_steps)}

### Recommended Commands
```bash
{chr(10).join(runbook.commands)}
```

### Metadata
- Risk Level: {runbook.risk_level}
- Estimated Duration: {runbook.estimated_duration}

**Follow these steps in order. Investigate before acting.**
"""
        return context

    def _format_list(self, items: List[str]) -> str:
        """Format list items with numbers."""
        if not items:
            return "- No specific steps documented"
        return "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))

    def list_runbooks(self) -> List[Dict]:
        """
        List all available runbooks.

        Returns:
            List of runbook summaries
        """
        return [
            {
                "alert_name": rb.alert_name,
                "title": rb.title,
                "risk_level": rb.risk_level,
                "command_count": len(rb.commands),
                "has_investigation": len(rb.investigation_steps) > 0,
                "has_remediation": len(rb.remediation_steps) > 0
            }
            for rb in self.runbooks.values()
        ]

    def reload(self) -> int:
        """
        Reload all runbooks from disk.

        Returns:
            Number of runbooks loaded
        """
        self.runbooks.clear()
        return self.load_runbooks()


# Global runbook manager instance
runbook_manager: Optional[RunbookManager] = None


def init_runbook_manager(runbook_dir: str = "/app/runbooks") -> RunbookManager:
    """
    Initialize global runbook manager.

    Args:
        runbook_dir: Directory containing runbook files

    Returns:
        RunbookManager instance
    """
    global runbook_manager
    runbook_manager = RunbookManager(runbook_dir=runbook_dir)
    runbook_manager.load_runbooks()
    return runbook_manager


def get_runbook_manager() -> Optional[RunbookManager]:
    """Get the global runbook manager instance."""
    return runbook_manager
