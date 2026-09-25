# RunPod Serverless Endpoint for Voice Cloning 

> **Fork com correcoes** (upstream: geronimi73/runpod_chatterbox)
>
> | Correcao | Motivo |
> |---|---|
> | Dockerfile pre-baixa o modelo com `device='cpu'` | A maquina de build do RunPod nao tem GPU; com `'cuda'` o build falha com exit code 1 |
> | `omegaconf` adicionado ao `requirements.txt` | `chatterbox-tts` e instalado com `--no-deps` e a lista manual estava desatualizada; `omegaconf` e importado no nivel de modulo em `models/s3gen/flow.py` |
> | Handler usa `ChatterboxMultilingualTTS` com `language_id` | O handler original usava `chatterbox.tts.ChatterboxTTS`, o modelo em **ingles**, e chamava `generate()` sem idioma. Texto em portugues saia com sotaque estrangeiro forte. O modelo multilingue suporta 23 idiomas e exige `language_id` |
> | `language` aceito no input (padrao `pt`) | Permite escolher o idioma por requisicao |
> | `exaggeration`, `cfg_weight`, `temperature` expostos no input | Ajuste fino da geracao sem rebuildar a imagem |


## Overview
* REST API
* Call Endpoint API with YouTube link and prompt
* Downloads first 60 seconds of provided YouTube audio
* Invokes [Chatterbox TTS model](https://github.com/resemble-ai/chatterbox) 
* Returns base64 encoded WAV audio

## Deploy 

* Get a RunPod account, maybe use my [referral link](https://runpod.io?ref=3lyngjfm)

Deploy endpoint ([docs](https://docs.runpod.io/serverless/overview#runpod-hub)):
* Go to https://console.runpod.io/serverless
* -> New Endpoint
* -> GitHub Repo, choose https://github.com/geronimi73/runpod_chatterbox
* Check `Endpoint ID` of your deployed endpoint at https://console.runpod.io/serverless
* Create an `API key` at https://console.runpod.io/user/settings

## Usage 

### JavaScript 

```js
const requestConfig = {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer " + RP_API_KEY
  },
  body: JSON.stringify({
    "input": {
      "prompt": "Hello world",
      "yt_url": "https://www.youtube.com/shorts/jcNzoONhrmE",
    }
  })
};
const url = "https://api.runpod.ai/v2/" + RP_ENDPOINT + "/runsync";
const response = await fetch(url, requestConfig);
let data = await response.json();
data = data.output

// audio data in data.audio_base64
```

## Issues
* Takes 3-4 Minutes to init worker
