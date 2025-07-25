#!/usr/bin/env python3
"""
Security Results Analyzer für SmartCity SensorBridge Partheland

Analysiert Security-Scan-Ergebnisse und erstellt Zusammenfassungen für GitHub Actions.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SecurityAnalyzer:
    """Analysiert Security-Scan-Ergebnisse"""

    def __init__(self):
        self.safety_report_path = "safety-report.json"
        self.bandit_report_path = "bandit-report.json"
        
    def analyze_safety_results(self) -> Tuple[bool, str, int, List[Dict]]:
        """Analysiert Safety-Dependency-Vulnerability-Ergebnisse"""
        if not os.path.exists(self.safety_report_path):
            return False, "none", 0, []
            
        try:
            with open(self.safety_report_path, 'r') as f:
                safety_data = json.load(f)
                
            vulnerabilities = safety_data.get('vulnerabilities', [])
            if not vulnerabilities:
                return False, "none", 0, []
                
            # Kategorisiere nach Schweregrad
            critical_count = 0
            high_count = 0
            medium_count = 0
            low_count = 0
            
            for vuln in vulnerabilities:
                severity = vuln.get('severity', 'unknown').lower()
                if severity == 'critical':
                    critical_count += 1
                elif severity == 'high':
                    high_count += 1
                elif severity == 'medium':
                    medium_count += 1
                elif severity == 'low':
                    low_count += 1
                    
            # Bestimme höchsten Schweregrad
            if critical_count > 0:
                severity = "critical"
            elif high_count > 0:
                severity = "high"
            elif medium_count > 0:
                severity = "medium"
            else:
                severity = "low"
                
            total_count = len(vulnerabilities)
            
            # Erstelle Details
            details = []
            for vuln in vulnerabilities[:5]:  # Maximal 5 für Issue
                details.append({
                    "package": vuln.get('package', 'unknown'),
                    "severity": vuln.get('severity', 'unknown'),
                    "description": vuln.get('description', 'No description'),
                    "cve": vuln.get('cve', 'N/A')
                })
                
            return True, severity, total_count, details
            
        except Exception as e:
            print(f"Fehler beim Analysieren der Safety-Ergebnisse: {e}", file=sys.stderr)
            return False, "error", 0, []
            
    def analyze_bandit_results(self) -> Tuple[bool, str, int, List[Dict]]:
        """Analysiert Bandit-Code-Security-Ergebnisse"""
        if not os.path.exists(self.bandit_report_path):
            return False, "none", 0, []
            
        try:
            with open(self.bandit_report_path, 'r') as f:
                bandit_data = json.load(f)
                
            results = bandit_data.get('results', [])
            if not results:
                return False, "none", 0, []
                
            # Kategorisiere nach Schweregrad
            high_count = 0
            medium_count = 0
            low_count = 0
            
            for result in results:
                severity = result.get('issue_severity', 'unknown').lower()
                if severity == 'high':
                    high_count += 1
                elif severity == 'medium':
                    medium_count += 1
                elif severity == 'low':
                    low_count += 1
                    
            # Bestimme höchsten Schweregrad
            if high_count > 0:
                severity = "high"
            elif medium_count > 0:
                severity = "medium"
            else:
                severity = "low"
                
            total_count = len(results)
            
            # Erstelle Details
            details = []
            for result in results[:5]:  # Maximal 5 für Issue
                details.append({
                    "file": result.get('filename', 'unknown'),
                    "line": result.get('line_number', 'unknown'),
                    "severity": result.get('issue_severity', 'unknown'),
                    "description": result.get('issue_text', 'No description'),
                    "test_id": result.get('test_id', 'N/A')
                })
                
            return True, severity, total_count, details
            
        except Exception as e:
            print(f"Fehler beim Analysieren der Bandit-Ergebnisse: {e}", file=sys.stderr)
            return False, "error", 0, []
            
    def analyze_all_results(self) -> Dict:
        """Analysiert alle Security-Ergebnisse"""
        # Analysiere Safety-Ergebnisse
        safety_has_vulns, safety_severity, safety_count, safety_details = self.analyze_safety_results()
        
        # Analysiere Bandit-Ergebnisse
        bandit_has_vulns, bandit_severity, bandit_count, bandit_details = self.analyze_bandit_results()
        
        # Kombiniere Ergebnisse
        has_vulnerabilities = safety_has_vulns or bandit_has_vulns
        total_count = safety_count + bandit_count
        
        # Bestimme höchsten Schweregrad
        severity_levels = {
            "critical": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
            "none": 0,
            "error": 0
        }
        
        max_severity = "none"
        max_level = 0
        
        for sev in [safety_severity, bandit_severity]:
            level = severity_levels.get(sev, 0)
            if level > max_level:
                max_level = level
                max_severity = sev
                
        # Erstelle Details-Text
        details_parts = []
        
        if safety_has_vulns:
            details_parts.append(f"**Dependency Vulnerabilities ({safety_count}):**")
            for detail in safety_details:
                details_parts.append(f"- {detail['package']} ({detail['severity']}): {detail['description']}")
                
        if bandit_has_vulns:
            details_parts.append(f"**Code Security Issues ({bandit_count}):**")
            for detail in bandit_details:
                details_parts.append(f"- {detail['file']}:{detail['line']} ({detail['severity']}): {detail['description']}")
                
        details_text = "\n".join(details_parts) if details_parts else "No vulnerabilities found"
        
        # GitHub Actions Output
        result = {
            "has-vulnerabilities": str(has_vulnerabilities).lower(),
            "severity": max_severity,
            "vulnerability-count": str(total_count),
            "details": details_text,
            "safety-count": str(safety_count),
            "bandit-count": str(bandit_count)
        }
        
        # Debug-Ausgabe
        print(f"Safety vulnerabilities: {safety_count} ({safety_severity})")
        print(f"Bandit issues: {bandit_count} ({bandit_severity})")
        print(f"Total issues: {total_count} ({max_severity})")
        print(f"Has vulnerabilities: {has_vulnerabilities}")
        
        # GitHub Actions Output setzen
        for key, value in result.items():
            print(f"::set-output name={key}::{value}")
            
        return result


def main():
    """Hauptfunktion"""
    analyzer = SecurityAnalyzer()
    result = analyzer.analyze_all_results()
    
    # Exit-Code basierend auf Schweregrad
    severity_levels = {
        "critical": 3,
        "high": 2,
        "medium": 1,
        "low": 0,
        "none": 0,
        "error": 1
    }
    
    exit_code = severity_levels.get(result["severity"], 0)
    sys.exit(exit_code)


if __name__ == "__main__":
    main() 