"""Runs real ComfyUI workflows on synthetic clips and proves the exact frames that came out.

Usage: python tests/e2e.py <comfy_port> <input_dir> <output_dir>
"""

import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

import av
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_clip import make_clip, read_file_indices, read_index  # noqa: E402

COMFY = f"http://127.0.0.1:{sys.argv[1]}"
INPUT, OUTPUT = sys.argv[2], sys.argv[3]
failures = []


def http(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        return {"http_status": e.code, **_json(e.read())}


def _json(raw):
    try:
        return json.loads(raw.decode())
    except ValueError:
        return {}


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'  ' + str(detail)[:400] if not condition else ''}", flush=True)
    if not condition:
        failures.append(name)


def run(workflow):
    response = http(f"{COMFY}/prompt", {"prompt": workflow})
    if "prompt_id" not in response:
        return {"validation": response}
    deadline = time.time() + 300
    while time.time() < deadline:
        history = http(f"{COMFY}/history/{response['prompt_id']}")
        if response["prompt_id"] in history:
            return history[response["prompt_id"]]
        time.sleep(0.25)
    return {"timeout": True}


def ok(result):
    return result.get("status", {}).get("status_str") == "success"


def error(result):
    if "validation" in result:
        return json.dumps(result["validation"])[:900]
    for name, data in result.get("status", {}).get("messages", []):
        if name == "execution_error":
            return data.get("exception_message", "")
    return json.dumps(result)[:400]


_counter = [0]


def saver(ref):
    _counter[0] += 1
    return f"e2e_{_counter[0]}", {"class_type": "SaveVideo", "inputs": {"video": ref, "filename_prefix": f"video/e2e_{_counter[0]}", "format": "mp4", "format.codec": "auto"}}


def saved(prefix):
    matches = sorted(glob.glob(os.path.join(OUTPUT, "video", f"{prefix}_*.mp4")))
    return matches[-1] if matches else ""


def indices(path, scale=1.0):
    return read_file_indices(path, scale)


def save_images_indices(result, node):
    images = result.get("outputs", {}).get(node, {}).get("images", [])
    from PIL import Image

    return [read_index(np.asarray(Image.open(os.path.join(OUTPUT, i["subfolder"], i["filename"])).convert("RGB"))) for i in images]


def load(parts="", file="clip.mp4"):
    return {"class_type": "RC_LoadVideo", "inputs": {"file": file, "parts": parts}}


def part(*pairs):
    return json.dumps([{"start": a, "end": b} for a, b in pairs])


def run_video(nodes, ref):
    prefix, node = saver(ref)
    result = run({**nodes, "save": node})
    return result, saved(prefix)


def has_audio_stream(path):
    with av.open(path) as container:
        return bool(container.streams.audio)


def audio_seconds(path):
    with av.open(path) as container:
        stream = container.streams.audio[0]
        total = sum(f.samples for f in container.decode(stream))
        return total / stream.codec_context.sample_rate


make_clip(os.path.join(INPUT, "clip.mp4"))
make_clip(os.path.join(INPUT, "other.mp4"), frames=48, fps=30, width=640, height=360, start=1000, audio=False)
make_clip(os.path.join(INPUT, "same.mp4"), frames=48, start=2000)
make_clip(os.path.join(INPUT, "clip.mkv"), frames=48)
INFO = http(f"{COMFY}/object_info")
for name in ["RC_LoadVideo", "RC_ImagesToVideo", "RC_VideoToImages", "RC_GrabFrame", "RC_CutVideo", "RC_JoinVideos", "RC_SpeedReverse", "RC_VideoAudio", "RC_VideoInfo", "RC_PreviewVideo"]:
    check(f"registered {name}", name in INFO)

# Load Video
result, path = run_video({"1": load()}, ["1", 0])
check("whole video when parts empty", ok(result) and indices(path) == list(range(240)), error(result))

result, path = run_video({"1": load(part((1.0, 3.0)))}, ["1", 0])
check("single part is frame exact", ok(result) and indices(path) == list(range(24, 72)), error(result) if not ok(result) else indices(path)[:4])

result, path = run_video({"1": load(part((6.5, 7.5), (1.0, 3.0)))}, ["1", 0])
check("multiple parts joined in time order", ok(result) and indices(path) == list(range(24, 72)) + list(range(156, 180)), error(result) if not ok(result) else indices(path)[44:52])

result = run({"1": load(part((1.0, 2.0), (3.0, 4.0))), "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 1], "filename_prefix": "load_img"}}})
check("IMAGE output matches the parts", ok(result) and save_images_indices(result, "2") == list(range(24, 48)) + list(range(72, 96)), error(result))

result = run({"1": load(part((1.0, 3.0))), "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 4]}}, "3": {"class_type": "PreviewAny", "inputs": {"source": ["1", 3]}}})
check("frames and fps outputs", ok(result) and result["outputs"]["2"]["text"][0] == "48" and float(result["outputs"]["3"]["text"][0]) == 24.0, error(result) if not ok(result) else result["outputs"])

result = run({"1": load(part((1.0, 3.0), (2.0, 4.0))), "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 4]}}})
check("overlapping parts refused", "overlap" in error(result), error(result))

# Connecting IMAGE later must not reuse the empty placeholder from an earlier run.
sel = part((2.0, 2.5))
_, first = run_video({"1": load(sel)}, ["1", 0])
result = run({"1": load(sel), "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 1], "filename_prefix": "late_img"}}})
check("IMAGE connected after a run gives real frames", ok(result) and save_images_indices(result, "2") == list(range(48, 60)), error(result) if not ok(result) else save_images_indices(result, "2"))

# Convert
make = {"1": load(part((0.0, 1.0)))}
result, path = run_video({**make, "2": {"class_type": "RC_ImagesToVideo", "inputs": {"images": ["1", 1], "timing": "frame rate", "timing.fps": 12.0}}}, ["2", 0])
check("images to video by fps", ok(result) and indices(path) == list(range(24)), error(result))
with av.open(path) as container:
    check("output fps honoured", float(container.streams.video[0].average_rate) == 12.0)

result, path = run_video({**make, "2": {"class_type": "RC_ImagesToVideo", "inputs": {"images": ["1", 1], "timing": "target seconds", "timing.seconds": 4.0}}}, ["2", 0])
with av.open(path) as container:
    stream = container.streams.video[0]
    check("images to video by target seconds", ok(result) and float(stream.average_rate) == 6.0, error(result))

result, path = run_video({**make, "a": load(part((0.0, 2.0))), "2": {"class_type": "RC_ImagesToVideo", "inputs": {"images": ["1", 1], "timing": "fit to audio", "audio": ["a", 2]}}}, ["2", 0])
with av.open(path) as container:
    check("images fit to audio length", ok(result) and abs(float(container.streams.video[0].average_rate) - 12.0) < 0.1 and has_audio_stream(path), error(result))

result = run({"1": load(), "2": {"class_type": "RC_VideoToImages", "inputs": {"video": ["1", 0], "start": 2.0, "end": 4.0, "every_nth": 4, "max_frames": 5, "longest_side": 0}}, "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "v2i"}}})
check("video to images every nth and max frames", ok(result) and save_images_indices(result, "3") == [48, 52, 56, 60, 64], error(result) if not ok(result) else save_images_indices(result, "3"))

result = run({"1": load(part((2.0, 4.0))), "2": {"class_type": "RC_VideoToImages", "inputs": {"video": ["1", 0], "start": 0.5, "end": 1.0, "every_nth": 1, "max_frames": 0, "longest_side": 160}}, "3": {"class_type": "PreviewAny", "inputs": {"source": ["2", 2]}}})
check("video to images respects an existing trim", ok(result) and result["outputs"]["3"]["text"][0] == "12", error(result) if not ok(result) else result["outputs"])

for label, position, expected in [("first", {"position": "first"}, 0), ("last", {"position": "last"}, 239), ("at time", {"position": "at time", "position.seconds": 5.0}, 120), ("at percent", {"position": "at percent", "position.percent": 50.0}, 120)]:
    result = run({"1": load(), "2": {"class_type": "RC_GrabFrame", "inputs": {"video": ["1", 0], **position}}, "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "grab"}}})
    check(f"grab frame {label}", ok(result) and save_images_indices(result, "3") == [expected], error(result) if not ok(result) else save_images_indices(result, "3"))

result = run({"1": load(part((2.0, 4.0))), "2": {"class_type": "RC_GrabFrame", "inputs": {"video": ["1", 0], "position": "last"}}, "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "grab"}}})
check("grab last frame of a trimmed part", ok(result) and save_images_indices(result, "3") == [95], error(result) if not ok(result) else save_images_indices(result, "3"))

result = run({"1": load(part((1.0, 2.0), (5.0, 6.0))), "2": {"class_type": "RC_GrabFrame", "inputs": {"video": ["1", 0], "position": "last"}}, "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "grab"}}})
check("grab last frame of multiple parts", ok(result) and save_images_indices(result, "3") == [143], error(result) if not ok(result) else save_images_indices(result, "3"))

# Edit
cut = {"1": load(part((1.0, 5.0))), "2": {"class_type": "RC_CutVideo", "inputs": {"video": ["1", 0], "seconds": 1.5}}}
prefix_a, save_a = saver(["2", 0])
prefix_b, save_b = saver(["2", 1])
result = run({**cut, "a": save_a, "b": save_b})
check("cut before", ok(result) and indices(saved(prefix_a)) == list(range(24, 60)), error(result))
check("cut after loses nothing", ok(result) and indices(saved(prefix_b)) == list(range(60, 120)), error(result))

result, path = run_video({"1": load(part((0.0, 1.0))), "2": load(file="same.mp4"), "3": {"class_type": "RC_JoinVideos", "inputs": {"videos.video_1": ["1", 0], "videos.video_2": ["2", 0], "crossfade": 0.0, "fit": "pad"}}}, ["3", 0])
check("join matching clips", ok(result) and indices(path) == list(range(24)) + list(range(2000, 2048)), error(result))

result, path = run_video({"1": load(part((0.0, 1.0))), "2": load(file="other.mp4"), "3": {"class_type": "RC_JoinVideos", "inputs": {"videos.video_1": ["1", 0], "videos.video_2": ["2", 0], "crossfade": 0.0, "fit": "stretch"}}}, ["3", 0])
if ok(result):
    out = indices(path)
    with av.open(path) as container:
        stream = container.streams.video[0]
        size = (stream.width, stream.height)
        rate = float(stream.average_rate)
    check("join conforms size and fps to first clip", size == (320, 180) and rate == 24.0, (size, rate))
    check("join mismatched keeps the first clip", out[:24] == list(range(24)), out[:26])
    with av.open(path) as container:
        rest = [read_index(f.to_ndarray(format="rgb24"), 0.5) for f in container.decode(video=0)][24:]
    check("join mismatched keeps the second clip in order", len(rest) in (38, 39) and rest[0] == 1000 and rest == sorted(rest) and rest[-1] >= 1046, (len(rest), rest[:3], rest[-3:]))
else:
    check("join mismatched run", False, error(result))

result, path = run_video({"1": load(part((0.0, 2.0))), "2": load(file="same.mp4"), "3": {"class_type": "RC_JoinVideos", "inputs": {"videos.video_1": ["1", 0], "videos.video_2": ["2", 0], "crossfade": 0.5, "fit": "pad"}}}, ["3", 0])
check("crossfade shortens by the overlap", ok(result) and len(indices(path)) == 48 + 48 - 12, error(result) if not ok(result) else len(indices(path)))
check("crossfade audio present", ok(result) and has_audio_stream(path))

result, path = run_video({"1": load(part((0.0, 4.0))), "2": {"class_type": "RC_SpeedReverse", "inputs": {"video": ["1", 0], "speed": 2.0, "reverse": False}}}, ["2", 0])
check("double speed takes every second frame", ok(result) and indices(path) == list(range(0, 96, 2)), error(result) if not ok(result) else indices(path)[:6])
check("double speed audio matches", ok(result) and abs(audio_seconds(path) - 2.0) < 0.1, audio_seconds(path) if ok(result) else "")

result, path = run_video({"1": load(part((0.0, 1.0))), "2": {"class_type": "RC_SpeedReverse", "inputs": {"video": ["1", 0], "speed": 0.5, "reverse": False}}}, ["2", 0])
check("half speed doubles frames", ok(result) and len(indices(path)) == 48 and indices(path)[:4] == [0, 0, 1, 1], error(result) if not ok(result) else indices(path)[:6])

result, path = run_video({"1": load(part((1.0, 2.0))), "2": {"class_type": "RC_SpeedReverse", "inputs": {"video": ["1", 0], "speed": 1.0, "reverse": True}}}, ["2", 0])
check("reverse order is exact", ok(result) and indices(path) == list(range(47, 23, -1)), error(result) if not ok(result) else indices(path)[:6])

# Audio
result, path = run_video({"1": load(part((0.0, 2.0))), "2": {"class_type": "RC_VideoAudio", "inputs": {"video": ["1", 0], "mode": "mute"}}}, ["2", 0])
check("mute removes the sound", ok(result) and not has_audio_stream(path), error(result))
check("mute keeps frames", ok(result) and indices(path) == list(range(48)))

result, path = run_video({"1": load(part((0.0, 2.0))), "s": load(part((0.0, 8.0))), "2": {"class_type": "RC_VideoAudio", "inputs": {"video": ["1", 0], "mode": "replace", "audio": ["s", 2]}}}, ["2", 0])
check("replace fits new sound to the video", ok(result) and has_audio_stream(path) and abs(audio_seconds(path) - 2.0) < 0.1, error(result) if not ok(result) else audio_seconds(path))
check("replace keeps frames", ok(result) and indices(path) == list(range(48)))

result = run({"1": load(part((0.0, 2.0))), "2": {"class_type": "RC_VideoAudio", "inputs": {"video": ["1", 0], "mode": "keep"}}, "3": {"class_type": "SaveAudio", "inputs": {"audio": ["2", 1], "filename_prefix": "audio/kept"}}})
check("keep outputs the video's sound", ok(result), error(result))

result, path = run_video({"1": load(file="other.mp4"), "s": load(part((0.0, 1.0))), "2": {"class_type": "RC_VideoAudio", "inputs": {"video": ["1", 0], "mode": "replace", "audio": ["s", 2]}}}, ["2", 0])
check("replace adds sound to a silent video", ok(result) and has_audio_stream(path), error(result))

# Info and preview
outs = {str(i): {"class_type": "PreviewAny", "inputs": {"source": ["2", i - 3]}} for i in range(3, 9)}
result = run({"1": load(part((1.0, 3.0), (6.5, 7.5))), "2": {"class_type": "RC_VideoInfo", "inputs": {"video": ["1", 0]}}, **outs})
if ok(result):
    values = [result["outputs"][str(i)]["text"][0] for i in range(3, 9)]
    check("video info", values[0] == "320" and values[1] == "180" and float(values[2]) == 24.0 and values[3] == "72" and abs(float(values[4]) - 3.0) < 0.05 and values[5].lower() == "true", values)
else:
    check("video info run", False, error(result))

result = run({"1": load(part((1.0, 2.0))), "2": {"class_type": "RC_PreviewVideo", "inputs": {"video": ["1", 0]}}})
preview = (result.get("outputs", {}).get("2") or {})
check("preview produces a temp video only", ok(result) and any(i.get("type") == "temp" for v in preview.values() if isinstance(v, list) for i in v if isinstance(i, dict)), error(result) if not ok(result) else preview)

# Routes
info = http(f"{COMFY}/roughcut/info?file=clip.mp4")
check("info route", abs(info.get("duration", 0) - 10.0) < 0.05 and info.get("fps") == 24.0 and info.get("frames") == 240, info)
for name in ["../comfyui_version.py", "..%5Cmain.py", "C:/Windows/win.ini", ""]:
    response = http(f"{COMFY}/roughcut/info?file={name}")
    check(f"route refuses {name or 'empty'}", response.get("http_status") == 404, response)
mkv = http(f"{COMFY}/roughcut/info?file=clip.mkv")
check("mkv is sent through the preview proxy", mkv.get("browser_playable") is False, mkv)
check("mkv length is exact", mkv.get("frames") == 48 and abs(mkv.get("duration", 0) - 2.0) < 0.001, mkv)
with urllib.request.urlopen(f"{COMFY}/roughcut/media?file=clip.mkv") as response:
    proxy = os.path.join(OUTPUT, "proxy_check.mp4")
    with open(proxy, "wb") as f:
        f.write(response.read())
with av.open(proxy) as container:
    check("proxy is a playable H.264 mp4", container.streams.video[0].codec.canonical_name == "h264" and len(list(container.decode(video=0))) == 48)
with urllib.request.urlopen(f"{COMFY}/roughcut/media?file=clip.mp4") as response:
    check("media route serves the file", response.status == 200 and len(response.read()) > 1000)
request = urllib.request.Request(f"{COMFY}/roughcut/media?file=clip.mp4", headers={"Range": "bytes=0-99"})
with urllib.request.urlopen(request) as response:
    check("media route supports seeking", response.status == 206 and len(response.read()) == 100)

print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed")
sys.exit(1 if failures else 0)
