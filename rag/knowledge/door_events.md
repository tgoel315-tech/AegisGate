# SOP — Door sensor events: forced door and door held open

## Forced door
The magnetic door contact reports DOOR_OPEN. If no authorised badge was tapped in the previous 6 seconds (the same rule the hardware script uses), AegisGate raises a FORCED_DOOR incident. A rejected badge tap followed by the door opening also counts as forced, because a rejected tap never opens an access session.

## Door held open
If the door stays open longer than the threshold (10 s by default, HELD_OPEN_THRESHOLD_S), AegisGate raises a DOOR_HELD_OPEN incident and updates it with the total open time when the door closes. This needs a door-closed event from the hardware. The restricted hardware script only sends DOOR_OPEN, so held-open detection turns on automatically the first time a DOOR_CLOSE event is received.

## Operator response — forced door
1. Send security to the door immediately; forced doors score highest.
2. Check the snapshot taken at the moment the door opened.
3. Look for an unauthorised entry or tailgating incident within the next minute; they will mention "Forced door nearby" in their risk breakdown.

## Operator response — door held open
1. Check whether people are passing through (crossings during the open period).
2. Ask the badge holder to close the door, or send someone to close it.
3. Repeated held-open incidents at the same gate may mean a faulty closer or a propped door.
