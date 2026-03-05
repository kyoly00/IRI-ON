import asyncio
import os
import json
import base64
import numpy as np
import pyaudio
from dotenv import load_dotenv
import os

from websockets import connect

load_dotenv()

class GeminiConnection:
    def __init__(self, config=None):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = "gemini-live-2.5-flash-preview"
        self.uri = (
            "wss://generativelanguage.googleapis.com/ws/"
            "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"
            f"?key={self.api_key}"
        )
        self.ws = None
        self.config = config or {
            "system_prompt": "너는 아동을 위한 친절하고 단계별 요리 보조 AI야. 모든 입출력은 한국어로만 해.",
            "voice": "Puck",
            "google_search": True
        }

    async def connect(self):
        self.ws = await connect(self.uri, additional_headers={"Content-Type": "application/json"})
        
        if not self.config:
            raise ValueError("Configuration must be set before connecting")

        setup_message = {
            "setup": {
                "model": f"models/{self.model}",
                "generation_config": {
                    "response_modalities": ["AUDIO"],  
                    "speech_config": {
                        "language_code": "ko-KR",
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": self.config["voice"]
                            },
                        }
                    }
                },
                'input_audio_transcription': {},
                'output_audio_transcription': {},
                "system_instruction": {
                    "parts": [
                        {
                            "text": self.config["system_prompt"]
                        }
                    ]
                }
            }
        }
        await self.ws.send(json.dumps(setup_message))

    def set_config(self, config):
        self.config = config

    async def send_audio(self, audio_data: str):
        """Base64 인코딩된 오디오 데이터를 전송"""
        realtime_input_msg = {
            "realtime_input": {
                "media_chunks": [
                    {
                        "data": audio_data,
                        "mime_type": "audio/pcm"
                    }
                ]
            }
        }
        await self.ws.send(json.dumps(realtime_input_msg))


    async def receive(self):
        """모델 응답 수신 (오디오+텍스트)"""
        input_transcriptions = []
        output_transcriptions = []
        responses = []

        async for raw_response in self.ws:   
            response = json.loads(raw_response.decode())
            server_content = response.pop("serverContent", None)
            if server_content is None:
                break

            if (input_transcription := server_content.get("inputTranscription")) is not None:
                if (text := input_transcription.get("text")) is not None:
                    input_transcriptions.append(text)

            if (output_transcription := server_content.get("outputTranscription")) is not None:
                if (text := output_transcription.get("text")) is not None:
                    output_transcriptions.append(text)

            model_turn = server_content.pop("modelTurn", None)
            if model_turn is not None:
                for part in model_turn.get("parts", []):
                    pcm_data = base64.b64decode(part["inlineData"]["data"])
                    responses.append(np.frombuffer(pcm_data, dtype=np.int32))

            if server_content.get("turnComplete"):
                break

        return {
            "input_transcriptions": input_transcriptions,
            "output_transcriptions": output_transcriptions,
            "audio": np.concatenate(responses) if responses else None
        }
    
    async def close(self):
        """Close the connection"""
        if self.ws:
            await self.ws.close()

    async def send_image(self, image_data: str):
        """Send image data to Gemini"""
        image_message = {
            "realtime_input": {
                "media_chunks": [
                    {
                        "data": image_data,
                        "mime_type": "image/jpeg"
                    }
                ]
            }
        }
        await self.ws.send(json.dumps(image_message))

    async def send_text(self, text: str):
        """Send text message to Gemini"""
        text_message = {
            "client_content": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": text}]
                    }
                ],
                "turn_complete": True
            }
        }
        await self.ws.send(json.dumps(text_message))
