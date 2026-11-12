"""Offlisten 在线演示：把一段音频转成带标点的文字，并报出 RTF。

这不是产品。产品是本地运行的桌面端（WASAPI 采集、不联网）；这里跑的是同一个
SenseVoice int8 模型在 Linux CPU 上的离线转写，用来证明模型与引擎的可用性。

设计约束：
- 免费 CPU Basic 档是 2 vCPU / 16 GB / 50 GB 非持久磁盘，容器会休眠后重建，
  所以模型不写进镜像，改为运行时从 Hub 拉取并缓存在容器内。
- 只接受 16 kHz 单声道交给模型；其它采样率在本地重采样，不依赖 ffmpeg。
- 所有失败都给出能照做的下一步，不返回 500。
"""

import os
import time

import gradio as gr
import numpy as np
import sherpa_onnx

MODEL_REPO = os.environ.get("OFFLISTEN_MODEL_REPO", "ToothpasteLake/offlisten-models")
MODEL_SUBDIR = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
TARGET_SR = 16000

_state = {"recognizer": None, "error": None, "lang": None}


def _find_model_files():
    """返回 (model_path, tokens_path)。优先用镜像内已有的目录，其次从 Hub 拉。"""
    local_dir = os.environ.get("OFFLISTEN_MODEL_DIR")
    if local_dir:
        m = os.path.join(local_dir, "model.int8.onnx")
        t = os.path.join(local_dir, "tokens.txt")
        if os.path.isfile(m) and os.path.isfile(t):
            return m, t
        raise RuntimeError("OFFLISTEN_MODEL_DIR 指向 %s，但里面没有 model.int8.onnx / tokens.txt" % local_dir)

    from huggingface_hub import hf_hub_download

    m = hf_hub_download(MODEL_REPO, "%s/model.int8.onnx" % MODEL_SUBDIR)
    t = hf_hub_download(MODEL_REPO, "%s/tokens.txt" % MODEL_SUBDIR)
    return m, t


def get_recognizer(language):
    """按语言惰性建识别器；同语言复用，避免每次请求都加载 229 MB。"""
    if _state["recognizer"] is not None and _state["lang"] == language:
        return _state["recognizer"]
    if _state["error"]:
        raise RuntimeError(_state["error"])
    try:
        model, tokens = _find_model_files()
        _state["recognizer"] = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model,
            tokens=tokens,
            language=language,
            use_itn=True,
            num_threads=int(os.environ.get("OFFLISTEN_THREADS", "2")),
        )
        _state["lang"] = language
        return _state["recognizer"]
    except Exception as e:
        _state["error"] = "%s: %s" % (type(e).__name__, e)
        raise


def _load_audio(path):
    """读成 float32 单声道 + 16 kHz。不依赖 ffmpeg。"""
    import soundfile as sf

    samples, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = samples.mean(axis=1)
    if sr != TARGET_SR and len(mono) > 1:
        n = int(round(len(mono) * TARGET_SR / float(sr)))
        mono = np.interp(
            np.linspace(0.0, len(mono) - 1, n), np.arange(len(mono)), mono
        ).astype(np.float32)
    return mono, TARGET_SR


def transcribe(audio_path, language):
    if not audio_path:
        return "", "先上传一段音频，或直接用麦克风录一句。"

    try:
        samples, sr = _load_audio(audio_path)
    except Exception as e:
        return "", (
            "读不了这个文件（%s）。请换成 wav / flac / ogg / mp3；"
            "如果是从会议软件导出的 m4a，先用任意工具转成 wav。" % e
        )

    duration = len(samples) / float(sr)
    if duration < 0.2:
        return "", "音频只有 %.2f 秒，太短了。" % duration

    try:
        recognizer = get_recognizer(language)
    except Exception as e:
        return "", (
            "模型没加载起来：%s\n\n"
            "常见原因：模型仓库还没推上去（`%s`），或该仓库是私有的而 Space 没有读权限。"
            % (e, MODEL_REPO)
        )

    started = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(sr, samples)
    recognizer.decode_stream(stream)
    elapsed = time.perf_counter() - started

    text = (stream.result.text or "").strip()
    if not text:
        return "", "这段音频里没识别出语音。确认它不是纯音乐或空白录音。"

    rtf = elapsed / duration if duration > 0 else float("nan")
    note = "音频 %.1f 秒，转写耗时 %.2f 秒，**RTF %.3f**（CPU Basic，2 vCPU，%s 线程）" % (
        duration,
        elapsed,
        rtf,
        os.environ.get("OFFLISTEN_THREADS", "2"),
    )
    return text, note


INTRO = """\
## 这是模型能力演示，不是产品

产品 **Offlisten** 在本地跑：抓系统声音、写本地文件、全程不联网。
这里把同一份 SenseVoice int8 模型放在服务器 CPU 上，只有一个目的——让你先听到效果，再决定要不要装。

- 模型：SenseVoice int8（中 / 英 / 日 / 韩 / 粤），229 MiB，自带标点与逆文本正则
- 语言选 `auto` 由模型自判；已知语种时指定会更稳
- 上传的音频只用于本次转写，不留存
"""


def build():
    with gr.Blocks(title="Offlisten ASR demo") as demo:
        gr.Markdown(INTRO)
        with gr.Row():
            with gr.Column():
                audio = gr.Audio(
                    sources=["upload", "microphone"],
                    type="filepath",
                    label="音频（wav / flac / ogg / mp3，任意采样率）",
                )
                language = gr.Dropdown(
                    ["auto", "zh", "en", "ja", "ko", "yue"],
                    value="auto",
                    label="语言",
                )
                run = gr.Button("转写", variant="primary")
            with gr.Column():
                text = gr.Textbox(label="转写结果", lines=10, show_copy_button=True)
                note = gr.Markdown()
        run.click(transcribe, inputs=[audio, language], outputs=[text, note])
        audio.change(transcribe, inputs=[audio, language], outputs=[text, note])
    return demo


if __name__ == "__main__":
    build().launch()
