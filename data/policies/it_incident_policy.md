# Enterprise IT Incident Response & Security Policy
Document ID: POL-IT-003
Department: IT
Access Role: it_admin, support, employee
Version: 1.8

## Section 1: Incident Severity Classification
IT incidents reported via user tickets or monitoring systems must be categorized within 15 minutes:
- Severity 1 (Critical): Total company-wide outage, data breach, or active ransomware infection. Requires immediate PagerDuty alert to SecOps and executive escalation.
- Severity 2 (Major): Service disruption affecting entire business unit (e.g., VPN outage, single production server degradation). Target resolution: 2 hours.
- Severity 3 (Minor / Standard): Single-user hardware or software defects (e.g., laptop monitor flicker, forgotten password). Target resolution: 24 business hours.

## Section 2: Account Provisioning and Privileges
Access to production infrastructure is governed strictly by Principle of Least Privilege:
- Standard software engineering accounts must never possess production database write privileges by default.
- Temporary emergency elevated credentials (Break-Glass access) require authorization from SecOps and expire automatically after 4 hours.

## Section 3: Hardware Refresh & Disposal
Hardware replacement tickets may only be approved for equipment older than 36 months or confirmed irreparable by Tier 2 Hardware Support technicians.
