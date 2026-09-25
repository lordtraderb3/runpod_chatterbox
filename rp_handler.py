"""RunPod serverless worker: Chatterbox multilingue com clonagem de voz.

Duas caracteristicas que o upstream nao tem:

1. A referencia de voz pode vir como audio direto (`audio_base64` ou
   `audio_url`), nao so como link do YouTube. Exigir YouTube inviabiliza
   producao: obrigaria o cliente a publicar a propria voz para ser clonado.

2. O embedding da referencia e preparado UMA vez por worker e reaproveitado
   nas chamadas seguintes. Sem isso, cada bloco de texto refaz o download e
   o calculo do embedding: num livro de 1.319 blocos isso foi medido em
   ~27 s de overhead por chamada, dois tercos do custo total de GPU.
"""
import base64
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

import runpod
import torchaudio
import yt_dlp
from chatterbox.mtl_tts import ChatterboxMultilingualTTS, SUPPORTED_LANGUAGES

model = None
DEFAULT_LANGUAGE = "pt"
PASTA_REF = Path("./referencia")

# Embedding ja carregado no modelo. Vive enquanto o worker viver.
referencia_atual = {"chave": None}


# --- referencia de voz ---------------------------------------------------

def chave_da_referencia(entrada):
    """Identifica a referencia SEM baixar nada.

    E o que permite pular o download quando o worker ja preparou esta voz.
    """
    if entrada.get("audio_base64"):
        digest = hashlib.sha256(entrada["audio_base64"].encode()).hexdigest()
        return f"b64:{digest[:32]}"
    if entrada.get("audio_url"):
        return f"url:{entrada['audio_url']}"
    if entrada.get("yt_url"):
        return f"yt:{entrada['yt_url']}"
    return None


def materializar_referencia(entrada, chave):
    """Grava a referencia em disco e devolve o caminho."""
    PASTA_REF.mkdir(parents=True, exist_ok=True)

    if chave.startswith("b64:"):
        destino = PASTA_REF / "ref.wav"
        destino.write_bytes(base64.b64decode(entrada["audio_base64"]))
        return str(destino)

    if chave.startswith("url:"):
        destino = PASTA_REF / "ref_baixada.wav"
        urllib.request.urlretrieve(entrada["audio_url"], destino)
        return str(destino)

    info, caminho = baixar_audio_youtube(
        entrada["yt_url"], output_path=str(PASTA_REF), audio_format="wav"
    )
    return caminho


def preparar_voz(entrada, chave, exaggeration):
    """Prepara o embedding se a referencia mudou. Devolve se reaproveitou."""
    if referencia_atual["chave"] == chave:
        return True

    caminho = materializar_referencia(entrada, chave)
    try:
        model.prepare_conditionals(caminho, exaggeration=exaggeration)
        referencia_atual["chave"] = chave
    finally:
        try:
            os.remove(caminho)
        except OSError:
            pass
    return False


# --- handler -------------------------------------------------------------

def handler(event, responseFormat="base64"):
    entrada = event["input"]
    prompt = entrada.get("prompt")
    if not prompt:
        return "informe 'prompt' com o texto a sintetizar"

    language_id = entrada.get("language", DEFAULT_LANGUAGE)
    if language_id not in SUPPORTED_LANGUAGES:
        return (
            f"idioma nao suportado: {language_id}. "
            f"Use um de: {sorted(SUPPORTED_LANGUAGES)}"
        )

    chave = chave_da_referencia(entrada)
    if chave is None:
        return "informe a referencia de voz em 'audio_base64', 'audio_url' ou 'yt_url'"

    exaggeration = float(entrada.get("exaggeration", 0.5))

    try:
        reaproveitou = preparar_voz(entrada, chave, exaggeration)

        # Sem audio_prompt_path: usa o embedding ja preparado.
        audio_tensor = model.generate(
            prompt,
            language_id=language_id,
            exaggeration=exaggeration,
            cfg_weight=float(entrada.get("cfg_weight", 0.5)),
            temperature=float(entrada.get("temperature", 0.8)),
        )
    except Exception as erro:
        print(f"Falha ao sintetizar: {erro}")
        return f"{erro}"

    audio_base64 = tensor_para_base64(audio_tensor, model.sr)

    if responseFormat == "binary":
        return audio_base64

    return {
        "status": "success",
        "audio_base64": audio_base64,
        "metadata": {
            "sample_rate": model.sr,
            "audio_shape": list(audio_tensor.shape),
            "language": language_id,
            # Permite ao cliente verificar que o cache esta funcionando.
            "reference_cached": reaproveitou,
            "reference_key": chave[:12],
        },
    }


def tensor_para_base64(audio_tensor, sample_rate):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as arquivo:
        caminho = arquivo.name
    try:
        torchaudio.save(caminho, audio_tensor, sample_rate)
        with open(caminho, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass


def initialize_model():
    global model
    if model is not None:
        print("Model already initialized")
        return model

    print("Initializing ChatterboxMultilingualTTS model...")
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
    print("Model initialized")


def baixar_audio_youtube(url, output_path="./downloads", audio_format="wav",
                         duration_limit=60):
    """Baixa o audio de um video do YouTube, cortado em `duration_limit` s."""
    Path(output_path).mkdir(parents=True, exist_ok=True)

    opcoes = {
        "format": "bestaudio/best",
        "outtmpl": f"{output_path}/output.%(ext)s",
        "quiet": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": "192",
        }],
        "postprocessor_args": ["-ar", "44100"],
        "prefer_ffmpeg": True,
    }
    if duration_limit:
        opcoes["postprocessor_args"].extend(["-t", str(duration_limit)])

    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=False)
        print(f"Referencia: {info.get('title', '?')} "
              f"({info.get('duration', '?')} s)")
        ydl.download([url])

    caminho = os.path.join(output_path, f"output.{audio_format}")
    if not os.path.exists(caminho):
        raise RuntimeError(f"download do YouTube nao produziu {caminho}")
    return info, caminho


if __name__ == "__main__":
    initialize_model()
    runpod.serverless.start({"handler": handler})
