import requests
from io import BytesIO


GENTLE_URL = "http://localhost:8765/transcriptions?async=false"



PHONEME_TO_VISEME = {
    "AA": "aa", "AE": "aa", "AH": "aa",
    "AO": "O", "OW": "O",
    "B": "PP", "P": "PP", "M": "PP",
    "CH": "CH", "JH": "CH",
    "D": "DD", "T": "DD",
    "DH": "TH", "TH": "TH",
    "EH": "E", "EY": "E",
    "ER": "RR",
    "F": "FF", "V": "FF", 
    "G": "kk", "K": "kk",
    "HH": "sil",
    "IH": "I", "IY": "I",
    "L": "RR",
    "N": "nn", "NG": "nn",
    "R": "RR",
    "S": "SS", "Z": "SS",
    "SH": "CH", "ZH": "CH",
    "UH": "U", "UW": "U",
    "W": "U",
    "Y": "I",
    "sil": "sil"
}

def gentle_align(wav_bytes, transcript):
    files = {
        "audio": ("speech.wav", BytesIO(wav_bytes), "audio/wav"),
        "transcript": (None, transcript)
    }
    resp = requests.post(GENTLE_URL, files=files)
    resp.raise_for_status()
    return resp.json()

def extract_word_timings(gentle_data):
    words, wtimes, wdurations = [], [], []
    for word in gentle_data.get("words", []):
        if word.get("case") != "success":
            continue
        w = word["word"]
        start = word["start"]
        end = word["end"]
        duration = end - start
        if w and start is not None and end is not None:
            words.append(w)
            wtimes.append(round(start, 3))
            wdurations.append(round(duration, 3))
    return words, wtimes, wdurations

def extract_visemes(gentle_data):
    visemes = []
    for word in gentle_data.get("words", []):
        if word.get("case") != "success":
            continue
        start_time = word["start"]
        acc = 0.0
        for phone in word.get("phones", []):
            phoneme = phone["phone"].split("_")[0].upper()
            duration = phone["duration"]
            vis_start = start_time + acc
            vis_end = vis_start + duration
            acc += duration
            viseme = PHONEME_TO_VISEME.get(phoneme)
            if viseme:
                visemes.append({
                    "viseme": viseme,
                    "start": round(vis_start, 3),
                    "end": round(vis_end, 3)
                })
    return visemes