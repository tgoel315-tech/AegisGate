"""
CCTV Anti-Tailgating & Gate Monitoring Configuration
"""

# Camera Source: 0 for default webcam, 1 for external CCTV/USB camera
CAMERA_SOURCE = 0

# Laterally invert (mirror horizontally) the camera feed
LATERALLY_INVERT = True

# Video resolution for optimal FPS and real-time inference
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# ----------------- Red Divider Line (Region Split) -----------------
# X position ratio in the middle (0.50 = 50% width, divides Left and Right regions vertically)
DIVIDER_LINE_X_RATIO = 0.50
DIVIDER_LINE_COLOR = (0, 0, 255)       # Pure Red BGR
DIVIDER_LINE_THICKNESS = 3
CORRIDOR_THRESHOLD_PX = 35             # Pixel tolerance band around the vertical red line

# ----------------- Access Control & Timing -----------------
TRANSIT_WINDOW_SECONDS = 4.0  # Seconds the gate remains authorized after a card tap
MAX_ALLOWED_PER_TAP = 1       # Number of people permitted to cross per card tap

# ----------------- Trajectory & Vector Settings -----------------
MIN_CROSSING_VELOCITY = 1.2   # Minimum downward velocity (px/frame) to qualify as active entering
LOITERING_VELOCITY_MAX = 0.8  # Velocity below which a person is flagged as stationary/loitering
TRAJECTORY_HISTORY_LEN = 12   # Number of past frames to track for movement vector calculation

# ----------------- Backend Integration -----------------
BACKEND_URL = "http://localhost:8000/api/event/vision"
EVENT_TIMEOUT = 0.5

# ----------------- Display Settings -----------------
WINDOW_TITLE = "AegisGate :: Smart CCTV Anti-Tailgating & Choke-Point Monitor"
