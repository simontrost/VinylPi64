# VinylPi64

VinylPi is a Raspberry Pi project that listens to audio from a turntable, identifies the currently playing song using **ShazamIO**, fetches album metadata and artwork, generates a **64×64 pixel frame**, and displays it on a **Divoom Pixoo-64**.

**Important: Hardware-specific implementation**

This project is built specifically for **my own hardware setup**:

- Raspberry Pi Zero 2 W  
- Audio-Technica **AT-LP120XUSB** (USB class-compliant turntable)  
- Divoom **Pixoo-64** (WiFi model)  

If you use different hardware, you will most likely have to modify parts of the code, like:
- **turntable without USB**: you will need a soundcard or USB microphone on your pi
- **other pixel display**: you need to modify the Divoom API calls

## Features

- Auto-detects USB audio device  
- USB audio capture from turntable  
- Automatic music recognition using **ShazamIO**  
- Album cover retrieval  
- Custom **64×64 pixel renderer**  
  - centered album cover  
  - Automatic contrasting color for artist/title  
  - white layout with spacing  
- Send results to pixel diplay
---

## Example Output


## Installation


### 0. Install OS on the Raspberry Pi

- I recommend using **Raspberry Pi OS Lite (64-bit)** for best performance (again I am using the Raspberry PI zero 2 w). 
- Flash it using the official [**Raspberry Pi Imager**](https://www.raspberrypi.com/software/).
- Enable SSH during flashing.  
- Boot the Pi and connect via SSH:

```bash
ssh user@hostname
```
### 1. Clone the repository
```bash
git clone https://github.com/simontrost/VinylPi64.git
cd VinylPi64
```
hint: you might need to `sudo apt install git` first

### 2. Create and activate a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
```
hint: you might need to `sudo apt install -y python3-venv python3-dev libportaudio2`first

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Check for your audio device:
```
arecord -l
```
eg:  `0 USB AUDIO CODEC: Audio (hw:0,0), ALSA (2 in, 2 out)`

### 5. Configuration:
```bash
nano config.json
```
- configure it as you want
- set at least the ip adress of your device (or subnet and let it detect)
- set the audio device you want to use
- optionally set a default image

## Licence 

Creative Commons Attribution–NonCommercial 4.0
- Allowed: use, modify, share
- Not allowed: commercial use

Full license text:
https://creativecommons.org/licenses/by-nc/4.0/legalcode.txt