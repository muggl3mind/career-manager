#!/usr/bin/env python3
"""
Todoist API Client
Handles all Todoist API interactions with proper endpoint (v1)
"""

import requests
import json
from pathlib import Path
from typing import List, Dict, Optional
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
from config_loader import get as config_get

# Paths - resolved via config.yaml
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CREDS_FILE = PROJECT_ROOT / config_get("credentials.todoist_token", ".credentials/todoist-token.json")

# API Configuration
BASE_URL = "https://api.todoist.com/api/v1"


def _check_enabled(func_name: str) -> bool:
    if not config_get("integrations.todoist_enabled", False):
        print(f"[todoist] Skipping {func_name} — todoist_enabled is false in config.yaml")
        return False
    return True


class TodoistClient:
    def __init__(self):
        """Initialize Todoist client with API token."""
        if not _check_enabled("TodoistClient"):
            self.token = None
            self.headers = {}
            return
        with open(CREDS_FILE, 'r') as f:
            self.token = json.load(f)['todoist_api_token']
        
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
    
    def get_tasks(self, project_id: Optional[str] = None) -> List[Dict]:
        """
        Get all active tasks, optionally filtered by project.
        
        Args:
            project_id: Optional project ID to filter by
            
        Returns:
            List of task dictionaries
        """
        url = f"{BASE_URL}/tasks"
        params = {}
        
        if project_id:
            params['project_id'] = project_id
        
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()

        data = response.json()
        # Todoist v1 endpoints may return either a list directly or an object with `results`
        if isinstance(data, list):
            return data
        return data.get('results', []) if isinstance(data, dict) else []
    
    def get_task(self, task_id: str) -> Dict:
        """Get a single task by ID."""
        url = f"{BASE_URL}/tasks/{task_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def add_task(self, content: str, project_id: Optional[str] = None, 
                 priority: int = 1, **kwargs) -> Dict:
        """
        Create a new task.
        
        Args:
            content: Task content/description
            project_id: Project to add task to
            priority: 1-4 (1=normal, 4=urgent)
            **kwargs: Additional task properties
            
        Returns:
            Created task dictionary
        """
        url = f"{BASE_URL}/tasks"
        
        data = {
            'content': content,
            'priority': priority,
            **kwargs
        }
        
        if project_id:
            data['project_id'] = project_id
        
        response = requests.post(url, headers=self.headers, json=data)
        response.raise_for_status()
        return response.json()
    
    def update_task(self, task_id: str, **kwargs) -> Dict:
        """
        Update an existing task.
        
        Args:
            task_id: ID of task to update
            **kwargs: Fields to update
            
        Returns:
            Updated task dictionary
        """
        url = f"{BASE_URL}/tasks/{task_id}"
        response = requests.post(url, headers=self.headers, json=kwargs)
        response.raise_for_status()
        return response.json()
    
    def complete_task(self, task_id: str) -> bool:
        """
        Mark a task as complete.
        
        Args:
            task_id: ID of task to complete
            
        Returns:
            True if successful
        """
        url = f"{BASE_URL}/tasks/{task_id}/close"
        response = requests.post(url, headers=self.headers)
        response.raise_for_status()
        return True
    
    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.
        
        Args:
            task_id: ID of task to delete
            
        Returns:
            True if successful
        """
        url = f"{BASE_URL}/tasks/{task_id}"
        response = requests.delete(url, headers=self.headers)
        response.raise_for_status()
        return True
    
    def get_projects(self) -> List[Dict]:
        """Get all projects."""
        url = f"{BASE_URL}/projects"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get('results', []) if isinstance(data, dict) else []


# Test if run directly
if __name__ == '__main__':
    client = TodoistClient()
    
    print("Testing Todoist API connection...")
    
    # Get all tasks
    tasks = client.get_tasks()
    print(f"\n✅ Found {len(tasks)} tasks")
    
    # Show first 5 tasks
    print("\nFirst 5 tasks:")
    for task in tasks[:5]:
        priority = '🔴' if task.get('priority') == 4 else '🟡' if task.get('priority') == 3 else '🟠' if task.get('priority') == 2 else '⚪'
        print(f"{priority} {task.get('content')}")
        print(f"   Project: {task.get('project_id')}")
        print(f"   Checked: {task.get('checked')}")
    
    # Get projects
    projects = client.get_projects()
    print(f"\n✅ Found {len(projects)} projects")
    for proj in projects:
        print(f"  - {proj.get('name')} (ID: {proj.get('id')})")
