# SOP — Tailgating and unauthorised entry response

## What counts as tailgating
Tailgating is when more people cross the doorway tripwire inbound than one authorised badge tap allows (default one person per tap). AegisGate pairs every inbound camera crossing with the access session opened by the most recent authorised tap. Each person beyond the allowance is an "extra person" on the same tailgating incident.

## What counts as unauthorised entry
An unauthorised entry is an inbound crossing with no authorised access session at all: nobody tapped a valid badge in the session window (8 s by default, plus a 3 s grace period for delayed camera events). AegisGate waits about 2 s before raising it in case the badge event arrives late.

## Operator response — tailgating
1. Open the incident in the live feed and download the PDF report.
2. Check the evidence snapshots: the first crossing is the badge holder, later ones are the extra people.
3. Contact the badge holder named in the incident and ask who entered with them.
4. If the extra person can't be identified as staff, send security to the secure area.
5. Record the outcome in your shift log with the incident id.

## Operator response — unauthorised entry
1. Treat it as a possible intrusion. Send security to the secure side of the door.
2. Use the snapshot to describe the person (clothing, direction). The camera doesn't identify people.
3. Check for a rejected badge tap or forced door just before the entry; those raise the risk score.

## Limitations to remember
The camera only counts people crossing a line; it can merge two people walking very close together into one track. Use the snapshots to confirm. AegisGate cannot lock the door, sound the buzzer or change LEDs. Those stay with the hardware.
