#!/usr/bin/env python3
"""
Add companies to tracker from daily opportunities
Helper script for morning digest workflow
"""

import sys
import json
from pathlib import Path

# Both scripts are in the same directory (job-tracker/scripts/)
from tracker_commands import add_application, get_company_data_from_research


def add_companies_to_tracker(company_names):
    """
    Add multiple companies to tracker.
    
    Args:
        company_names: List of company names or single company name
    
    Returns:
        List of results
    """
    if isinstance(company_names, str):
        company_names = [company_names]
    
    results = []
    
    for company_name in company_names:
        # Get research data to find role
        research_data = get_company_data_from_research(company_name)
        
        # Determine role from research or use generic
        role = "Multiple roles (see careers page)"
        
        # Determine priority from fit score
        fit_score_text = research_data.get('fit_score', '').lower().strip()
        priority = 1 if fit_score_text in ['excellent', 'very high'] else 2
        
        # Add to tracker
        result = add_application(
            company=company_name,
            role=role,
            priority=priority,
            job_url=research_data.get('job_url', '')
        )
        
        results.append(result)
    
    return results


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: add_to_tracker.py <company1> [company2] [company3] ...")
        sys.exit(1)
    
    companies = sys.argv[1:]
    results = add_companies_to_tracker(companies)
    
    for result in results:
        print(result['message'])
        if result['success'] and result.get('research_data'):
            data = result['research_data']
            if data.get('tech_signals'):
                print(f"  Tech: {data['tech_signals'][:80]}...")
            if data.get('stage'):
                print(f"  Stage: {data['stage']}")
