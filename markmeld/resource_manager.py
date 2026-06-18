"""Resource Manager for markmeld package.

This module provides a unified interface for managing embedded resources including:
- Lua filters for pandoc
- Jinja templates for document generation
- CSL files for citation formatting

The ResourceManager class discovers and provides paths to all embedded resources,
making them available as variables in command templates.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional


class ResourceManager:
    """Manages embedded resources (filters, templates, CSL files) for markmeld.

    This class provides methods to discover, list, and retrieve paths for all
    embedded resources that are packaged with markmeld. Resources are made
    available as variables that can be used in command templates.

    Attributes:
        base_path: Path to the markmeld package directory.
        resource_dirs: Dictionary mapping resource types to their directories.
    """

    def __init__(self) -> None:
        """Initialize the ResourceManager with resource type paths."""
        self.base_path = Path(__file__).parent
        self.resource_dirs: Dict[str, Path] = {
            "filter": self.base_path / "filters",
            "template": self.base_path / "templates",
            "csl": self.base_path / "csl",
        }

        self._resource_cache: Dict[str, Dict[str, str]] = {}
        self._discover_all_resources()

    def _discover_all_resources(self) -> None:
        """Discover all available resources and cache their paths."""
        self._discover_filters()
        self._discover_templates()
        self._discover_csl_files()

    def _discover_filters(self) -> None:
        """Discover all available Lua filters."""
        filters_dir = self.resource_dirs["filter"]
        if not filters_dir.exists():
            self._resource_cache["filter"] = {}
            return

        filters: Dict[str, str] = {}
        for subdir in filters_dir.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("__"):
                lua_files = list(subdir.glob("*.lua"))
                if lua_files:
                    # Map filter directory names to their main .lua files
                    lua_file_mapping = {
                        "change-marker": "change_marker.lua",
                        "consistent-citations": "consistent-citations.lua",
                        "figczar": "figczar.lua",
                        "multi-refs": "multi-refs.lua",
                        "supplement": "supplement.lua",
                        "supplemental-labels": "supplemental_labels.lua",
                    }

                    # Try the mapping first
                    if subdir.name in lua_file_mapping:
                        lua_file = subdir / lua_file_mapping[subdir.name]
                        if lua_file.exists():
                            filters[subdir.name] = str(lua_file.absolute())
                            continue

                    # Fall back to finding any .lua file
                    if len(lua_files) == 1:
                        filters[subdir.name] = str(lua_files[0].absolute())
                    else:
                        # If multiple, try to find one that matches the filter name
                        for lua_file in lua_files:
                            if (
                                subdir.name.replace("-", "_") in lua_file.stem
                                or subdir.name.replace("-", "") in lua_file.stem
                            ):
                                filters[subdir.name] = str(lua_file.absolute())
                                break
                        else:
                            # Default to the first one
                            filters[subdir.name] = str(lua_files[0].absolute())

        self._resource_cache["filter"] = filters

    def _discover_templates(self) -> None:
        """Discover all available Jinja templates recursively."""
        templates_dir = self.resource_dirs["template"]
        if not templates_dir.exists():
            self._resource_cache["template"] = {}
            return

        templates: Dict[str, str] = {}

        def scan_directory(directory: Path, prefix: str = "") -> None:
            """Recursively scan directory for .jinja files.

            Args:
                directory: Directory to scan.
                prefix: Prefix for template names from parent directories.
            """
            for item in directory.iterdir():
                if item.is_file() and item.suffix == ".jinja":
                    name_parts = []
                    if prefix:
                        name_parts.append(prefix)
                    name_parts.append(item.stem)
                    template_name = "-".join(name_parts)
                    templates[template_name] = str(item.absolute())
                elif item.is_dir() and not item.name.startswith("__"):
                    new_prefix = f"{prefix}-{item.name}" if prefix else item.name
                    scan_directory(item, new_prefix)

        scan_directory(templates_dir)
        self._resource_cache["template"] = templates

    def _discover_csl_files(self) -> None:
        """Discover all available CSL files."""
        csl_dir = self.resource_dirs["csl"]
        if not csl_dir.exists():
            self._resource_cache["csl"] = {}
            return

        csl_files: Dict[str, str] = {}
        for csl_file in csl_dir.glob("*.csl"):
            csl_name = csl_file.stem
            csl_files[csl_name] = str(csl_file.absolute())

        self._resource_cache["csl"] = csl_files

    def list_resources(self, resource_type: str) -> List[str]:
        """List all available resources of a given type.

        Args:
            resource_type: Type of resource ("filter", "template", or "csl").

        Returns:
            Sorted list of resource names.
        """
        if resource_type not in self._resource_cache:
            return []
        return sorted(self._resource_cache[resource_type].keys())

    def get_resource_path(self, resource_type: str, resource_name: str) -> Optional[str]:
        """Get the absolute path to a specific resource.

        Args:
            resource_type: Type of resource ("filter", "template", or "csl").
            resource_name: Name of the resource.

        Returns:
            Absolute path to the resource, or None if not found.
        """
        if resource_type not in self._resource_cache:
            return None
        return self._resource_cache[resource_type].get(resource_name)

    def validate_resource(self, resource_type: str, resource_name: str) -> bool:
        """Check if a resource exists.

        Args:
            resource_type: Type of resource ("filter", "template", or "csl").
            resource_name: Name of the resource.

        Returns:
            True if resource exists, False otherwise.
        """
        return self.get_resource_path(resource_type, resource_name) is not None

    def get_all_resource_variables(self) -> Dict[str, str]:
        """Get all resource variables for command substitution.

        Returns a dictionary mapping variable names like {mm-filter-name},
        {mm-template-name}, and {mm-csl-name} to their absolute paths.

        Returns:
            Dictionary of variable names to resource paths.
        """
        variables: Dict[str, str] = {}

        # Add filter variables
        for filter_name, filter_path in self._resource_cache.get("filter", {}).items():
            variables[f"mm-filter-{filter_name}"] = filter_path

        # Add template variables
        for template_name, template_path in self._resource_cache.get(
            "template", {}
        ).items():
            variables[f"mm-template-{template_name}"] = template_path

        # Add CSL variables
        for csl_name, csl_path in self._resource_cache.get("csl", {}).items():
            variables[f"mm-csl-{csl_name}"] = csl_path

        return variables


# Convenience functions for common resource operations


def list_filters() -> List[str]:
    """List all available filter names.

    Returns:
        List of filter names.
    """
    rm = ResourceManager()
    return rm.list_resources("filter")


def get_filter_path(filter_name: str) -> Optional[str]:
    """Get the absolute path to a specific filter.

    Args:
        filter_name: Name of the filter.

    Returns:
        Absolute path to the filter, or None if not found.
    """
    rm = ResourceManager()
    return rm.get_resource_path("filter", filter_name)


def inject_resource_variables(target_dict: Dict) -> Dict:
    """Inject all embedded resource variables into a target dictionary.

    This function adds all available resource variables (filters, templates,
    CSL files) to the provided dictionary, making them available for variable
    substitution.

    Args:
        target_dict: Dictionary to inject variables into (typically target.meta).

    Returns:
        The updated dictionary with resource variables added.
    """
    rm = ResourceManager()
    resource_vars = rm.get_all_resource_variables()
    target_dict.update(resource_vars)
    return target_dict
