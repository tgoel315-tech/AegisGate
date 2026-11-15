# AegisGate system overview

## Components
AegisGate is an edge-AI anti-tailgating sentry for one access-controlled door. The ESP32-S3 hardware (RFID reader, magnetic door contact, I2S speaker, LEDs) sends BADGE_TAP and DOOR_OPEN events to the backend. A laptop webcam runs a YOLOv8n person detector with ByteTrack multi-object tracking and reports each person crossing a virtual tripwire as IN or OUT with a unique track id. The FastAPI backend correlates the three sources, scores risk and stores evidence. The Streamlit dashboard shows everything live over a WebSocket.

## Entry and exit log
Each authorised entry creates a record with the badge holder and time in. An outbound crossing closes the oldest open record with a time out.

## Evidence
For every incident AegisGate keeps the timestamps, badge id and holder, every camera crossing with its track id and snapshot, door open and close times, and the full risk breakdown. A PDF report can be downloaded from the live feed on the right side of the dashboard.

## Privacy
The camera tracks movement and counts crossings. It does not recognise faces or identify anyone. Names come only from the badge database.
