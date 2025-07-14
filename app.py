from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for
import openai
from openai import OpenAI
import os
from gtts import gTTS
from io import BytesIO
from deepgram import DeepgramClient, SpeakOptions
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, url_for
import json
import re
import time
from gentle_utils import gentle_align, extract_visemes, extract_word_timings
# from force_align import forcealign_align, extract_word_timings, extract_visemes 
from avatar_config import AVATAR_VOICE_MAP
from greetings import GREETINGS_MAP
import traceback
import random
import tempfile
import json
from datetime import datetime
import mimetypes
from google.cloud import texttospeech_v1beta1 as tts
from g2p_en import G2p
from collections import defaultdict
import logging

############################################################################
# CONFIGURATION AND SETUP
############################################################################

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# In-memory store: { avatar_name : [ {role: ..., content: ...}, ... ] }
conversation_histories = defaultdict(list)

mimetypes.add_type('application/javascript', '.mjs')

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Load environment variables
load_dotenv()

############################################################################
# FLASK APP INITIALIZATION
############################################################################

app = Flask(__name__)
app.secret_key = 'thisisasecretkey'

############################################################################
# API CONFIGURATION
############################################################################

# API Keys from environment
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google-creds.json")

# TTS Provider from environment (default to openai if not specified)
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "deepgram").lower()

# Validate TTS provider
if TTS_PROVIDER not in ["openai", "google", "deepgram"]:
    logger.warning(f"Invalid TTS_PROVIDER '{TTS_PROVIDER}'. Defaulting to 'openai'")
    TTS_PROVIDER = "openai"

logger.info(f"Using TTS Provider: {TTS_PROVIDER}")

############################################################################
# API CLIENT INITIALIZATION
############################################################################

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize Google Cloud credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

# Initialize Deepgram client if API key is available
if DEEPGRAM_API_KEY:
    deepgram_client = DeepgramClient(DEEPGRAM_API_KEY)

############################################################################
# TTS GENERATION FUNCTIONS
############################################################################

def generate_openai_tts(text, voice):
    """
    Generate TTS using OpenAI's text-to-speech API
    
    Args:
        text (str): Text to convert to speech
        voice (str): Voice model to use (e.g., 'alloy', 'echo', 'fable')
    
    Returns:
        bytes: Audio content in WAV format
    """
    try:
        tts_response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="wav"
        )
        logger.info(f"OpenAI TTS generated successfully for text length: {len(text)}")
        return tts_response.content
    except Exception as e:
        logger.error(f"Error generating OpenAI TTS: {e}")
        raise

def generate_google_tts(text, voice_config):
    """
    Generate TTS using Google Cloud Text-to-Speech API
    
    Args:
        text (str): Text to convert to speech
        voice_config (dict): Voice configuration containing language_code and voice
    
    Returns:
        bytes: Audio content in MP3 format
    """
    try:
        client_tts = tts.TextToSpeechClient()
        synthesis_input = tts.SynthesisInput(text=text)
        voice_params = tts.VoiceSelectionParams(
            language_code=voice_config["language_code"],
            name=voice_config["voice"]
        )
        audio_config = tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3)
        
        response = client_tts.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config
        )
        logger.info(f"Google TTS generated successfully for text length: {len(text)}")
        return response.audio_content
    except Exception as e:
        logger.error(f"Error generating Google TTS: {e}")
        raise

def generate_deepgram_tts(text, voice_model):
    """
    Generate TTS using Deepgram's text-to-speech API
    
    Args:
        text (str): Text to convert to speech
        voice_model (str): Deepgram voice model to use
    
    Returns:
        bytes: Audio content in WAV format
    """
    try:
        TEXT = {"text": text}
        file_path = os.path.join(os.getcwd(), "static", 'temp.wav')
        tts_options = SpeakOptions(model=voice_model, container="wav", encoding="linear16")
        deepgram_client.speak.v("1").save(file_path, TEXT, tts_options)
        
        with open(file_path, 'rb') as f:
            audio_content = f.read()
        
        logger.info(f"Deepgram TTS generated successfully for text length: {len(text)}")
        return audio_content
    except Exception as e:
        logger.error(f"Error generating Deepgram TTS: {e}")
        raise

def generate_tts_audio(text, avatar_config):
    """
    Generate TTS audio based on the configured provider with fallback support
    
    Args:
        text (str): Text to convert to speech
        avatar_config (dict): Avatar configuration containing TTS settings for all providers
    
    Returns:
        bytes: Audio content
    """
    try:
        if TTS_PROVIDER == 'openai':
            return generate_openai_tts(text, avatar_config['openai'])
        elif TTS_PROVIDER == 'google':
            return generate_google_tts(text, avatar_config['google'])
        elif TTS_PROVIDER == 'deepgram':
            return generate_deepgram_tts(text, avatar_config['deepgram'])
        else:
            # Fallback to OpenAI
            logger.warning(f"Unknown TTS provider: {TTS_PROVIDER}. Falling back to OpenAI.")
            return generate_openai_tts(text, avatar_config['openai'])
    except Exception as e:
        logger.error(f"Error with {TTS_PROVIDER} TTS: {e}")
        # Fallback to OpenAI if the configured provider fails
        if TTS_PROVIDER != 'openai':
            logger.info("Falling back to OpenAI TTS")
            return generate_openai_tts(text, avatar_config['openai'])
        else:
            raise e

############################################################################
# ROUTE HANDLERS - MAIN PAGES
############################################################################

@app.route("/")
def main():
    """Main landing page for avatar selection"""
    return render_template("main.html")

@app.route('/select-avatar')
def select_avatar():
    """Handle avatar selection and redirect to appropriate interface"""
    avatar = request.args.get('avatar')
    if not avatar:
        return redirect(url_for('main'))
    session['selected_avatar'] = avatar
    logger.info(f"Avatar selected: {avatar}")
    return redirect(url_for('index'))

@app.route('/call')
def call():
    """Render the call interface (video call with avatar)"""
    avatar = session.get('selected_avatar') or request.args.get('avatar')
    if not avatar:
        return redirect(url_for('main'))
    logger.info(f"Loading call interface for avatar: {avatar}")
    return render_template('call.html', avatar=avatar)

@app.route('/chat')
def chat():
    """Render the chat interface (text-based chat with avatar)"""
    avatar = session.get('selected_avatar') or request.args.get('avatar')
    if not avatar:
        return redirect(url_for('main'))
    logger.info(f"Loading chat interface for avatar: {avatar}")
    return render_template('chat.html', avatar=avatar)

############################################################################
# ROUTE HANDLERS - CLEAR CONVERSATION
############################################################################

@app.route('/end_convo', methods=['POST'])
def end_convo():
    """End conversation and clear session data"""
    try:
        session.clear()
        logger.info("Conversation ended and session cleared")
        return jsonify({'message': ''}), 200
    except Exception as e:
        logger.error(f"Error ending conversation: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/clear', methods=['POST'])
def clear():
    """Clear all conversation histories"""
    conversation_histories.clear()
    logger.info("All conversation histories cleared")
    return jsonify({"status": "cleared"}), 204

############################################################################
# ROUTE HANDLERS - TEXT AND AUDIO PROCESSING TO GET RESPONSE FROM GPT
############################################################################

@app.route('/process_text', methods=['POST'])
def process_text():
    """
    Process text input from user and generate AI response with TTS
    Used for chat interface
    """
    start_time = time.time()
    
    try:
        data = request.get_json()
        user_text = data.get('message', '')
        avatar = data.get('avatar', 'avatar1.glb')
        
        if not user_text.strip():
            return jsonify({'error': 'No message provided'}), 400
        
        logger.info(f"Processing text input from user: {user_text[:50]}...")
        
        voice_params = AVATAR_VOICE_MAP.get(avatar)
        
        # Retrieve this avatar's conversation history
        history = conversation_histories[avatar]
        
        # Append user message to history
        history.append({"role": "user", "content": user_text})
        history[:] = history[-20:]
        messages = [{"role": "system", "content": voice_params["system_prompt"] + " You are chatting with user. Respond as you are directly speaking to user. Do not include special characters in responses. Only generate speech output as you are directly talking to user. Make sure the output has proper structure like using ... for better text to speech"}]
        messages.extend(history)
        
        # Generate AI response
        chat = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.5,
            messages=messages
        )
        
        response = chat.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": response})
        
        logger.info(f"AI response generated: {response[:50]}...")
        
        # Generate TTS using the configured provider
        avatar_config = AVATAR_VOICE_MAP.get(avatar, AVATAR_VOICE_MAP['avatar1.glb'])
        audio_content = generate_tts_audio(response, avatar_config)
        
        # Save audio file
        audio_path = os.path.join(os.getcwd(), "static", 'temp.wav')
        with open(audio_path, 'wb') as f:
            f.write(audio_content)
        
        # Store response text for metadata
        session['last_response_text'] = response
        cleaned_response = response.replace("...", "")
        
        end_time = time.time()
        logger.info(f"Text processing completed in {end_time - start_time:.2f} seconds")
        
        return jsonify({
            'response': cleaned_response,
            'audio_ready': True,
            'message': 'Text processed successfully'
        })
        
    except Exception as e:
        logger.error(f"Error in process_text: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/process_audio', methods=['POST'])
def process_audio():
    """
    Process audio input from user, transcribe it, and generate AI response
    Used for voice call interface
    """
    start_time = time.time()
    
    try:
        audio = request.files['audio']
        avatar = request.form.get('avatar', 'avatar1.glb')
        
        logger.info(f"Processing audio input for avatar: {avatar}")
        
        # Save audio to temporary file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            audio.save(temp_file.name)
            temp_path = temp_file.name
        
        # Transcribe audio using OpenAI Whisper
        with open(temp_path, 'rb') as audio_data:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_data,
                response_format="json"
            )
        
        user_text = transcript.text
        logger.info(f"Audio transcribed: {user_text}")
        
        # Clean up temporary file
        os.unlink(temp_path)
        
        voice_params = AVATAR_VOICE_MAP.get(avatar)

        # Retrieve this avatar's conversation history
        history = conversation_histories[avatar]

        # Append user message to history
        history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": voice_params["system_prompt"] + " You are on a call with user. Respond as you are directly speaking to user. Do not include special characters in responses. Only generate speech output as you are directly talking to user.Make sure the output has proper structure like using ... for better text to speech"}]
        messages.extend(history)

        # Generate AI response
        chat = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=messages
        )
        response = chat.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": response})
        history[:] = history[-20:]
        
        logger.info(f"AI response generated: {response[:50]}...")
        
        # Generate TTS using the configured provider
        avatar_config = AVATAR_VOICE_MAP.get(avatar, AVATAR_VOICE_MAP['avatar1.glb'])
        audio_content = generate_tts_audio(response, avatar_config)
        
        # Save audio file
        audio_path = os.path.join(os.getcwd(), "static", 'temp.wav')
        with open(audio_path, 'wb') as f:
            f.write(audio_content)
        
        # Store response text for metadata
        session['last_response_text'] = response
        
        end_time = time.time()
        logger.info(f"Audio processing completed in {end_time - start_time:.2f} seconds")
        
        return jsonify({'message': 'Audio processed successfully', 'audio_ready': True})
        
    except Exception as e:
        logger.error(f"Error in process_audio: {e}")
        return jsonify({'error': str(e)}), 500

############################################################################
# ROUTE HANDLERS - AUDIO AND METADATA SERVING
############################################################################

@app.route('/get_response_audio')
def get_response_audio():
    """Serve the generated audio response file"""
    try:
        audio_path = os.path.join(os.getcwd(), 'static', 'temp.wav')
        if os.path.exists(audio_path):
            return send_file(audio_path, as_attachment=False, mimetype='audio/wav')
        else:
            logger.error("Audio file not found")
            return jsonify({'error': 'Audio file not found'}), 404
    except Exception as e:
        logger.error(f"Error serving audio file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_response_metadata')
def get_response_metadata():
    """
    Generate and serve metadata for avatar lip-sync animation
    Includes word timings and viseme data
    """
    try:
        # Path to audio (must match what you send in /get_response_audio)
        audio_path = os.path.join(os.getcwd(), 'static', 'temp.wav')
        if not os.path.exists(audio_path):
            logger.error("Audio file not found for metadata generation")
            return jsonify({'error': 'Audio file not found'}), 404

        # Load audio bytes for alignment
        with open(audio_path, "rb") as f:
            wav_bytes = f.read()

        # Load last generated response text
        text = session.get('last_response_text')
        if not text:
            logger.error("No response text in session for metadata generation")
            return jsonify({'error': 'No response text in session'}), 400

        # Run alignment to generate lip-sync data using gentle
        gentle_data = gentle_align(wav_bytes, text)
        words, wtimes, wdurations = extract_word_timings(gentle_data)
        visemes = extract_visemes(gentle_data)


        # # Run alignment to generate lip-sync data using force align
        # word_alignments, phoneme_alignments = forcealign_align(text)
        # words, wtimes, wdurations = extract_word_timings(word_alignments)
        # visemes = extract_visemes(phoneme_alignments)

        logger.info("Metadata generated successfully for lip-sync animation")

        # Return metadata for frontend
        return jsonify({
            "words": words,
            "wtimes": wtimes,
            "wdurations": wdurations,
            "visemes": visemes
        })

    except Exception as e:
        logger.error(f"Error generating metadata: {e}")
        return jsonify({'error': str(e)}), 500

############################################################################
# ROUTE HANDLERS - INITIAL GREETING SYSTEM ON CALL
############################################################################

@app.route('/get_initial_greeting')
def get_initial_greeting():
    """
    Get a random initial greeting audio file for the selected avatar
    Based on avatar gender and pre-recorded greeting files
    """
    try:
        avatar = request.args.get('avatar', 'avatar1.glb')
        avatar_config = AVATAR_VOICE_MAP.get(avatar, AVATAR_VOICE_MAP['avatar1.glb'])
        gender_key = avatar_config['gender']
        
        logger.info(f"Getting initial greeting for avatar: {avatar} (gender: {gender_key})")
        
        greeting_folder = os.path.join('static', 'greetings', gender_key)
        if not os.path.exists(greeting_folder):
            logger.error(f"Greeting folder not found for gender: {gender_key}")
            return jsonify({"error": f"Greeting folder not found for gender: {gender_key}"}), 404

        greeting_files = [f for f in os.listdir(greeting_folder) if f.endswith('.wav')]
        if not greeting_files:
            logger.error("No greeting files found")
            return jsonify({"error": "No greeting files found"}), 404
        
        selected_greeting = random.choice(greeting_files)
        greeting_url = url_for('static', filename=f"greetings/{gender_key}/{selected_greeting}", _external=True)
        metadata = GREETINGS_MAP.get(gender_key, {}).get(selected_greeting)

        logger.info(f"Selected greeting: {selected_greeting}")

        return jsonify({
            "audio_url": greeting_url,
            "metadata": metadata
        })
        
    except Exception as e:
        logger.error(f"Error getting initial greeting: {e}")
        return jsonify({'error': str(e)}), 500

############################################################################
# APPLICATION STARTUP
############################################################################

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    app.run(debug=True)