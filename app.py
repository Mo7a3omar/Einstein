from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from functools import wraps
import os
import google.generativeai as genai
import requests
import tempfile
import time
import subprocess
from dotenv import load_dotenv
import speech_recognition as sr

# Load environment variables
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
heygen_api_key = os.getenv("HEYGEN_API_KEY")

if gemini_api_key:
    os.environ["GEMINI_API_KEY"] = gemini_api_key
    genai.configure(api_key=gemini_api_key)

avatar_id = "22e57a238de540c39d17b9abbcb814dd"
voice_id = "7f3cf16f222240eead2e712ff3a91a77"

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)  # Required for sessions
sessions = {}

# Password for accessing the application
APP_PASSWORD = "Aiavaholomagic*0608!"

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password')
        if password == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = "Invalid password. Please try again."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

def get_headers():
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "x-api-key": heygen_api_key
    }

def convert_to_wav(input_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_input:
        temp_input.write(input_bytes)
        temp_input_path = temp_input.name
    temp_output = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_output_path = temp_output.name
    temp_output.close()
    command = [
        'ffmpeg', '-y', '-i', temp_input_path,
        '-ac', '1', '-ar', '16000', '-f', 'wav',
        '-loglevel', 'error', temp_output_path
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
        with open(temp_output_path, 'rb') as f:
            wav_bytes = f.read()
        return wav_bytes, temp_output_path
    except Exception as e:
        print(f"Error converting audio: {e}")
        return None, None
    finally:
        try: os.unlink(temp_input_path)
        except: pass

def process_audio_with_google(audio_data, language_hint):
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.6
    wav_bytes, temp_path = convert_to_wav(audio_data)
    if not wav_bytes:
        return None
    try:
        with sr.AudioFile(temp_path) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.1)
            audio = recognizer.record(source)
            try:
                if language_hint == 'Korean':
                    return recognizer.recognize_google(audio, language="ko-KR")
                else:
                    return recognizer.recognize_google(audio, language="en-US")
            except sr.UnknownValueError:
                return None
            except sr.RequestError as e:
                print(f"Google Speech Recognition error: {e}")
                return None
    finally:
        if temp_path:
            try: os.unlink(temp_path)
            except: pass

heygen_session = requests.Session()

def create_session():
    url = "https://api.heygen.com/v1/streaming.new"
    payload = {
        "quality": "medium",
        "avatar_id": avatar_id,
        "voice": {"voice_id": voice_id, "rate": 1},
        "video_encoding": "VP8",
        "disable_idle_timeout": False,
        "version": "v2"
    }
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=5)
        print(f"HeyGen API response status: {response.status_code}")
        print(f"HeyGen API response body: {response.text}")
        response.raise_for_status()
        session_data = response.json()
        if 'data' in session_data and 'session_id' in session_data['data']:
            return session_data['data']
    except Exception as e:
        print(f"Error creating session: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Error response: {e.response.text}")
    return None

def start_session(session_id):
    url = "https://api.heygen.com/v1/streaming.start"
    payload = {"session_id": session_id}
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=5)
        response.raise_for_status()
        start_data = response.json()
        return start_data.get('code') == 100 or start_data.get('message') == 'success'
    except Exception as e:
        print(f"Error starting session: {e}")
        return False

def stop_heygen_session(session_id):
    url = "https://api.heygen.com/v1/streaming.stop"
    payload = {"session_id": session_id}
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=5)
        print(f"HeyGen stop response: {response.status_code} - {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error stopping HeyGen session: {e}")
        return False

def send_message_to_avatar(session_id, text):
    url = "https://api.heygen.com/v1/streaming.task"
    payload = {"session_id": session_id, "text": text}
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=5)
        response.raise_for_status()
        return response.json().get('data', {})
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def initialize_einstein_bot():
    system_instruction = """You are AI Einstein, a friendly science buddy for kids! Your job is to make science super fun and easy to understand.
    - Keep your responses under 100 words to ensure they don't exceed 1 minutes of speaking time
    - Use simple words and be enthusiastic
    - Give concise, exciting answers
    - Respond in Korean if the user speaks Korean
    - Always prioritize brevity while maintaining educational value"""
    
    model = genai.GenerativeModel('gemini-2.0-flash-exp', system_instruction=system_instruction)
    chat = model.start_chat(history=[])
    return chat

def get_einstein_response(chat, user_message, language_hint):
    try:
        if language_hint == 'Korean':
            prompt = f"질문: {user_message}\n(대답은 반드시 한국어로 해주세요)"
        else:
            prompt = user_message
        response = chat.send_message(prompt)
        return response.text
    except Exception as e:
        print(f"Error getting Einstein response: {e}")
        return "Sorry, I didn't catch that. Could you repeat your question?"

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/session/create', methods=['POST'])
@login_required
def api_create_session():
    interface_language = request.json.get('interface_language', 'en')
    session_data = create_session()
    if session_data:
        session_id = session_data['session_id']
        sessions[session_id] = {
            'access_token': session_data['access_token'],
            'url': session_data['url'],
            'chat': initialize_einstein_bot(),
            'last_interaction': time.time(),
            'language': 'Korean' if interface_language == 'ko' else 'English',
            'active': True
        }
        if start_session(session_id):
            greeting = "안녕하세요! 저는 아인슈타인입니다. 과학에 대해 무엇이든 물어보세요!" if interface_language == 'ko' else "Hello! I'm Einstein. Ask me anything about science!"
            send_message_to_avatar(session_id, greeting)
            return jsonify({
                'success': True,
                'session_id': session_id,
                'access_token': session_data['access_token'],
                'url': session_data['url']
            })
    return jsonify({'success': False, 'error': 'Failed to create session'})

@app.route('/api/process_audio', methods=['POST'])
@login_required
def api_process_audio():
    session_id = request.form.get('session_id')
    if not session_id or session_id not in sessions or not sessions[session_id].get('active'):
        return jsonify({'success': False, 'error': 'Invalid or inactive session'})
    audio_file = request.files.get('audio')
    if not audio_file:
        return jsonify({'success': False, 'error': 'No audio file'})
    audio_data = audio_file.read()
    interface_language = request.form.get('interface_language', 'en')
    language_hint = 'Korean' if interface_language == 'ko' else 'English'
    user_input = process_audio_with_google(audio_data, language_hint)
    if not user_input:
        return jsonify({'success': False, 'error': 'Failed to process audio'})
    session = sessions[session_id]
    session['last_interaction'] = time.time()
    response_text = get_einstein_response(session['chat'], user_input, language_hint)
    send_message_to_avatar(session_id, response_text)
    return jsonify({
        'success': True,
        'user_input': user_input,
        'response': response_text
    })

@app.route('/api/session/stop', methods=['POST'])
@login_required
def api_stop_session():
    data = request.json
    session_id = data.get('session_id')
    if session_id and session_id in sessions:
        stop_heygen_session(session_id)
        sessions[session_id]['active'] = False
        sessions.pop(session_id)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Failed to stop session'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
