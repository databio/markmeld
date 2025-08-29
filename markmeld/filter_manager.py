import os
from pathlib import Path
from typing import List, Optional


def get_filters_dir() -> Path:
    """Get the path to the filters directory."""
    return Path(__file__).parent / "filters"


def list_filters() -> List[str]:
    """
    List all available filter names by scanning subdirectories.
    
    Returns:
        List of filter names (directory names containing .lua files)
    """
    filters_dir = get_filters_dir()
    if not filters_dir.exists():
        return []
    
    filter_names = []
    for subdir in filters_dir.iterdir():
        if subdir.is_dir() and not subdir.name.startswith('__'):
            # Check if directory contains any .lua files
            lua_files = list(subdir.glob("*.lua"))
            if lua_files:
                filter_names.append(subdir.name)
    
    return sorted(filter_names)


def get_filter_path(filter_name: str) -> Optional[str]:
    """
    Get the absolute path to the main .lua file for a specific filter.
    
    Args:
        filter_name: Name of the filter (directory name)
        
    Returns:
        Absolute path to the main .lua file, or None if filter not found
    """
    filters_dir = get_filters_dir()
    filter_dir = filters_dir / filter_name
    
    if not filter_dir.exists() or not filter_dir.is_dir():
        return None
    
    # Map filter directory names to their main .lua files
    lua_file_mapping = {
        "change-marker": "change_marker.lua",
        "figczar": "figczar.lua",
        "multi-refs": "multi-refs.lua",
        "supplemental-labels": "supplemental_labels.lua"
    }
    
    # Try the mapping first
    if filter_name in lua_file_mapping:
        lua_file = filter_dir / lua_file_mapping[filter_name]
        if lua_file.exists():
            return str(lua_file.absolute())
    
    # Fall back to finding any .lua file
    lua_files = list(filter_dir.glob("*.lua"))
    if lua_files:
        # If there's only one .lua file, return it
        if len(lua_files) == 1:
            return str(lua_files[0].absolute())
        # If multiple, try to find one that matches the filter name
        for lua_file in lua_files:
            if filter_name.replace("-", "_") in lua_file.stem or filter_name.replace("-", "") in lua_file.stem:
                return str(lua_file.absolute())
        # Default to the first one
        return str(lua_files[0].absolute())
    
    return None


def validate_filter_name(filter_name: str) -> bool:
    """
    Check if a filter exists.
    
    Args:
        filter_name: Name of the filter to validate
        
    Returns:
        True if filter exists, False otherwise
    """
    return get_filter_path(filter_name) is not None