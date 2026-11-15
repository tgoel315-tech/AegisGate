# How the AegisGate risk score works

## Overview
The risk score is rule-based and transparent, from 0 to 100. No machine learning or LLM decides it. Every incident stores the list of factors that produced its score, and the PDF report prints them.

## Base points per incident type
Rejected badge 15. Door held open 25. Tailgating 45. Unauthorised entry 55. Forced door 60.

## Additional factors
Each extra person beyond the first extra adds 15 points (max 30) for tailgating or group unauthorised entry. A forced door in the last 60 seconds adds 15 to people-related incidents. Each rejected badge attempt in the last 5 minutes adds 10 (max 20). A door being held open during an entry adds 10. Each other incident at the gate in the last 10 minutes adds 5 (max 15). For door-held-open incidents, every 15 seconds beyond the limit adds 5 (max 20). The total is capped at 100.

## Severity bands
LOW 0-24, MEDIUM 25-49, HIGH 50-74, CRITICAL 75-100.

## Gate risk score
The gate score shown on the dashboard is the highest recent incident score, decayed linearly over 15 minutes, plus 20 percent of the other decayed incident scores. It returns to 0 when nothing has happened for 15 minutes.
