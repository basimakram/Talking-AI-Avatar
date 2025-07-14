#Alternative to Gentle

from forcealign import ForceAlign
import tempfile
import re
import os

PHONEME_TO_VISEME = {
    "SIL": "sil",
    "P": "PP", "B": "PP", "M": "PP",
    "F": "FF", "V": "FF",
    "TH": "TH", "DH": "TH",
    "D": "DD", "T": "DD",
    "G": "kk", "K": "kk",
    "CH": "CH", "JH": "CH",
    "S": "SS", "Z": "SS",
    "N": "nn", "NG": "nn",
    "R": "RR", "L": "RR",
    "AA": "aa", "AE": "aa", "AH": "aa",
    "EH": "E", "EY": "E",
    "IH": "I", "IY": "I", "Y": "I",
    "AO": "O", "OW": "O",
    "UH": "U", "UW": "U", "W": "U"
}


def forcealign_align(transcript):
    # Write audio bytes to temp file (ForceAlign expects a wav file)
    # with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
    #     tmp.write(wav_bytes)
    #     audio_path = tmp.name
    # Set path to the audio file in static directory
    audio_path = os.path.join('static', 'temp.wav')

    # Load the WAV file as bytes
    with open(audio_path, 'rb') as f:
        wav_bytes = f.read()
    # Create ForceAlign object and run alignment
    align = ForceAlign(audio_file=audio_path, transcript=transcript)
    # Run alignment (you still need to call this method to do the alignment)
    align.inference()
    # Return alignments directly
    return align.word_alignments, align.phoneme_alignments

def extract_word_timings(word_alignments):
    word_list = []
    word_starts = []
    word_durations = []

    for w in word_alignments:
        word_list.append(w.word)
        word_starts.append(round(w.time_start, 3))
        word_durations.append(round(w.time_end - w.time_start, 3))
    return word_list, word_starts, word_durations

def extract_visemes(phoneme_alignments):
    visemes = []
    for p in phoneme_alignments:
        # Strip digits from phoneme (e.g. EY1 -> EY)
        phoneme = re.sub(r'\d', '', p.phoneme.upper())
        viseme = PHONEME_TO_VISEME.get(phoneme)
        if viseme:
            visemes.append({
                "viseme": viseme,
                "end": round(p.time_start, 3),
                "start": round(p.time_end, 3)
            })
    return visemes