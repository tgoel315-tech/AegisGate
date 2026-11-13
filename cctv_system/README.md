# AegisGate — Live CCTV Monitor with Vertical Red Divider Line

A real-time CCTV computer vision engine with:
1. **Live Camera Feed**: Direct webcam/USB CCTV capture with DirectShow optimization on Windows.
2. **Laterally Inverted (Mirror Mode)**: Horizontally flipped (`cv2.flip(frame, 1)`) so movement mirrors naturally.
3. **Vertical Red Divider Line in the Middle**: Positioned vertically at $X = W / 2$, dividing:
   - **Region 1 (Left Side of Red Line)**: Public approach corridor where people or groups can roam and loiter freely with **0 false alarms**.
   - **Region 2 (Right Side of Red Line)**: Secure/restricted interior.
4. **Anti-Tailgating & Access Control**:
   - Tapping an RFID badge opens a **4.0-second transit window** (+1 entry credit).
   - When a person crosses from **Left to Right across the Vertical Red Line**:
     - If matched with a badge tap $\to$ **`ACCESS VERIFIED`** (Green).
     - If crossed with zero badge taps OR a second person follows without a tap $\to$ **`ALARM: TAILGATING / UNAUTHORIZED CROSSING!`** in flashing Red!

---

## 🚀 How to Run

```bash
cd cctv_system
python cctv_engine.py
```

*(If you use an external USB CCTV/webcam instead of built-in, run `python cctv_engine.py --source 1`)*

---

## ⌨️ Interactive Controls

| Key | Action |
| :--- | :--- |
| **`t` or `SPACEBAR`** | **Simulate Card / Badge Tap** (Opens 4.0s transit window, +1 Credit) |
| **`a` or `w`** | Move Vertical Red Divider Line **LEFT** |
| **`d` or `z`** | Move Vertical Red Divider Line **RIGHT** |
| **`f`** | **Toggle Mirror Mode** (Lateral Invert ON / OFF) |
| **`c`** | Reset all counters back to 0 |
| **`p`** | Capture manual snapshot to backend |
| **`q` or `ESC`** | Quit application |
