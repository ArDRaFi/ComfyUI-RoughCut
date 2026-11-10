import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_ID = "RC_LoadVideo";
const WIDGET_HEIGHT = 340;

const stylesheet = document.createElement("link");
stylesheet.rel = "stylesheet";
stylesheet.href = new URL("./timeline.css", import.meta.url).href;
document.head.appendChild(stylesheet);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function timecode(seconds) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(2).padStart(5, "0")}`;
}

function attachTimeline(node) {
  const partsWidget = node.widgets.find((w) => w.name === "parts");
  const fileWidget = node.widgets.find((w) => w.name === "file");
  if (!partsWidget || !fileWidget) return;

  // The text box stays as the saved value, and is what the backend reads.
  partsWidget.hidden = true;

  const root = element("div", "rc-root");
  const video = element("video", "rc-video");
  video.preload = "auto";
  video.playsInline = true;

  const transport = element("div", "rc-row");
  const previousButton = element("button", "", "<");
  const playButton = element("button", "", "Play parts");
  const nextButton = element("button", "", ">");
  const timeLabel = element("span", "rc-time", "0:00.00 / 0:00.00");
  previousButton.title = "Back one frame";
  nextButton.title = "Forward one frame";
  transport.append(previousButton, playButton, nextButton, timeLabel);

  const track = element("div", "rc-track");
  const playhead = element("div", "rc-playhead");

  const actions = element("div", "rc-row");
  const addButton = element("button", "", "+ Add part");
  const deleteButton = element("button", "", "Delete part");
  const setStartButton = element("button", "", "Set start");
  const setEndButton = element("button", "", "Set end");
  actions.append(addButton, deleteButton, setStartButton, setEndButton);

  const fields = element("div", "rc-row");
  const startInput = element("input");
  const endInput = element("input");
  startInput.type = endInput.type = "number";
  startInput.min = endInput.min = "0";
  fields.append(element("span", "", "start"), startInput, element("span", "", "end"), endInput, element("span", "", "seconds"));

  const summary = element("div", "rc-summary", "Choose a video");

  const source = element("div", "rc-row");
  const uploadButton = element("button", "", "Upload video");
  const picker = element("input");
  picker.type = "file";
  picker.accept = "video/*,.mkv,.mov,.avi,.webm";
  picker.style.display = "none";
  source.append(uploadButton, picker);

  root.append(source, video, transport, track, actions, fields, summary);

  node.addDOMWidget("rc_timeline", "roughcut", root, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => WIDGET_HEIGHT,
  });
  node.setSize([Math.max(node.size[0], 440), Math.max(node.size[1], node.computeSize()[1])]);

  let info = null;
  let parts = [];
  let selected = 0;
  let playing = false;
  let frameRequest = 0;
  let loadToken = 0;
  let drag = null;

  const frameLength = () => (info ? 1 / info.fps : 0.04);
  const snap = (seconds) => (info ? Math.round(seconds * info.fps) / info.fps : seconds);
  const duration = () => info?.duration ?? 0;
  const clampTime = (seconds) => Math.min(Math.max(seconds, 0), duration());

  function save() {
    const whole = parts.length === 1 && parts[0].start <= frameLength() / 2 && parts[0].end >= duration() - frameLength() / 2;
    const value = whole ? "" : JSON.stringify(parts.map((p) => ({ start: +p.start.toFixed(6), end: +p.end.toFixed(6) })));
    if (partsWidget.value !== value) {
      partsWidget.value = value;
      node.graph?.setDirtyCanvas?.(true);
    }
  }

  function showError(message) {
    summary.textContent = message;
    summary.classList.add("rc-error");
  }

  function renderSummary() {
    summary.classList.remove("rc-error");
    const total = parts.reduce((sum, p) => sum + (p.end - p.start), 0);
    const frames = Math.round(total * info.fps);
    summary.textContent = `${parts.length} ${parts.length === 1 ? "part" : "parts"}, ${total.toFixed(2)}s of ${duration().toFixed(2)}s, ${frames} frames`;
  }

  function renderTime() {
    const now = video.currentTime || 0;
    timeLabel.textContent = `${timecode(now)} / ${timecode(duration())}`;
    playhead.style.left = duration() ? `${(now / duration()) * 100}%` : "0";
  }

  function render() {
    track.replaceChildren();
    if (!info) return;
    parts.forEach((part, index) => {
      const bar = element("div", index === selected ? "rc-part rc-selected" : "rc-part");
      bar.dataset.index = index;
      bar.style.left = `${(part.start / duration()) * 100}%`;
      bar.style.width = `${((part.end - part.start) / duration()) * 100}%`;
      const startHandle = element("div", "rc-handle rc-handle-start");
      const endHandle = element("div", "rc-handle rc-handle-end");
      startHandle.dataset.edge = "start";
      endHandle.dataset.edge = "end";
      bar.append(startHandle, endHandle);
      track.append(bar);
    });
    track.append(playhead);
    const part = parts[selected];
    startInput.value = part.start.toFixed(3);
    endInput.value = part.end.toFixed(3);
    startInput.step = endInput.step = frameLength().toFixed(4);
    deleteButton.disabled = parts.length <= 1;
    renderSummary();
    renderTime();
  }

  function changed() {
    save();
    render();
  }

  function setEdge(index, edge, seconds) {
    const part = parts[index];
    const minimum = frameLength();
    const time = snap(seconds);
    if (edge === "start") {
      const floor = index > 0 ? parts[index - 1].end : 0;
      part.start = Math.max(floor, Math.min(time, part.end - minimum));
    } else {
      const ceiling = index < parts.length - 1 ? parts[index + 1].start : duration();
      part.end = Math.min(ceiling, Math.max(time, part.start + minimum));
    }
  }

  function movePart(index, start) {
    const part = parts[index];
    const length = part.end - part.start;
    const floor = index > 0 ? parts[index - 1].end : 0;
    const ceiling = index < parts.length - 1 ? parts[index + 1].start : duration();
    const moved = Math.max(floor, Math.min(snap(start), ceiling - length));
    part.start = moved;
    part.end = moved + length;
  }

  function seek(seconds) {
    video.currentTime = clampTime(seconds);
    renderTime();
  }

  function timeAt(clientX) {
    const box = track.getBoundingClientRect();
    return clampTime(((clientX - box.left) / box.width) * duration());
  }

  track.addEventListener("pointerdown", (event) => {
    if (!info) return;
    event.stopPropagation();
    event.preventDefault();
    track.setPointerCapture(event.pointerId);
    const bar = event.target.closest?.(".rc-part");
    if (!bar) {
      drag = { kind: "seek" };
      seek(timeAt(event.clientX));
      return;
    }
    selected = Number(bar.dataset.index);
    const edge = event.target.dataset?.edge;
    if (edge) {
      drag = { kind: "edge", edge };
    } else {
      drag = { kind: "move", offset: timeAt(event.clientX) - parts[selected].start };
    }
    render();
  });

  track.addEventListener("pointermove", (event) => {
    if (!drag) return;
    event.stopPropagation();
    const time = timeAt(event.clientX);
    if (drag.kind === "seek") {
      seek(time);
    } else if (drag.kind === "edge") {
      setEdge(selected, drag.edge, time);
      seek(parts[selected][drag.edge]);
      changed();
    } else {
      movePart(selected, time - drag.offset);
      changed();
    }
  });

  const endDrag = (event) => {
    if (!drag) return;
    event.stopPropagation();
    drag = null;
  };
  track.addEventListener("pointerup", endDrag);
  track.addEventListener("pointercancel", endDrag);

  async function upload(file) {
    summary.classList.remove("rc-error");
    summary.textContent = `Uploading ${file.name}...`;
    const form = new FormData();
    form.append("image", file, file.name);
    try {
      const response = await api.fetchApi("/upload/image", { method: "POST", body: form });
      if (!response.ok) throw new Error(String(response.status));
      const result = await response.json();
      const name = result.subfolder ? `${result.subfolder}/${result.name}` : result.name;
      const values = fileWidget.options.values;
      if (!values.includes(name)) values.push(name);
      fileWidget.value = name;
      fileWidget.callback?.(name);
    } catch {
      showError("The upload failed.");
    }
  }

  uploadButton.onclick = () => picker.click();
  picker.onchange = () => {
    if (picker.files?.[0]) upload(picker.files[0]);
    picker.value = "";
  };
  node.onDragOver = (event) => [...(event.dataTransfer?.types ?? [])].includes("Files");
  node.onDragDrop = (event) => {
    const file = [...(event.dataTransfer?.files ?? [])].find((f) => f.type.startsWith("video/") || /\.(mkv|mov|avi|webm|mp4|m4v)$/i.test(f.name));
    if (!file) return false;
    upload(file);
    return true;
  };

  for (const control of [source, transport, actions, fields]) {
    control.addEventListener("pointerdown", (event) => event.stopPropagation());
  }

  function freeSpace() {
    const gaps = [];
    let cursor = 0;
    parts.forEach((part, index) => {
      if (part.start - cursor >= frameLength() * 2) gaps.push({ start: cursor, end: part.start, after: index });
      cursor = part.end;
    });
    if (duration() - cursor >= frameLength() * 2) gaps.push({ start: cursor, end: duration(), after: parts.length });
    return gaps;
  }

  function addPart() {
    if (!info) return;
    const gaps = freeSpace();
    const gap = gaps.find((g) => g.after > selected) ?? gaps[0];
    if (gap) {
      const margin = Math.min(frameLength() * 2, (gap.end - gap.start) / 4);
      const start = snap(gap.start + (gap.start > 0 ? margin : 0));
      const end = Math.min(snap(start + Math.max(1, (gap.end - gap.start) / 2)), gap.end);
      parts.splice(gap.after, 0, { start, end: Math.max(end, start + frameLength()) });
      selected = gap.after;
    } else {
      // No free space, so split the selected part at the playhead, or in the middle.
      const part = parts[selected];
      const length = part.end - part.start;
      const gapLength = Math.max(frameLength(), Math.min(1, length * 0.1));
      if (length < frameLength() + gapLength + frameLength()) return;
      const now = video.currentTime || 0;
      const inside = now > part.start + frameLength() && now < part.end - gapLength - frameLength();
      const split = snap(inside ? now : part.start + length / 2);
      const nextStart = snap(split + gapLength);
      const end = part.end;
      part.end = split;
      parts.splice(selected + 1, 0, { start: nextStart, end });
      selected += 1;
    }
    changed();
    seek(parts[selected].start);
  }

  addButton.onclick = addPart;
  deleteButton.onclick = () => {
    if (parts.length <= 1) return;
    parts.splice(selected, 1);
    selected = Math.min(selected, parts.length - 1);
    changed();
  };
  setStartButton.onclick = () => {
    if (!info) return;
    setEdge(selected, "start", video.currentTime);
    changed();
  };
  setEndButton.onclick = () => {
    if (!info) return;
    setEdge(selected, "end", video.currentTime);
    changed();
  };
  startInput.onchange = () => {
    if (!info) return;
    setEdge(selected, "start", Number(startInput.value) || 0);
    changed();
    seek(parts[selected].start);
  };
  endInput.onchange = () => {
    if (!info) return;
    setEdge(selected, "end", Number(endInput.value) || 0);
    changed();
    seek(parts[selected].end);
  };
  previousButton.onclick = () => seek(snap((video.currentTime || 0) - frameLength()));
  nextButton.onclick = () => seek(snap((video.currentTime || 0) + frameLength()));

  function stopPlaying() {
    playing = false;
    video.pause();
    cancelAnimationFrame(frameRequest);
    playButton.textContent = "Play parts";
    renderTime();
  }

  function playStep() {
    if (!playing) return;
    const now = video.currentTime;
    const inside = parts.find((p) => now >= p.start - 0.001 && now < p.end);
    if (!inside) {
      const next = parts.find((p) => p.start > now);
      if (next) {
        video.currentTime = next.start;
      } else {
        video.currentTime = parts[0].start;
        stopPlaying();
        return;
      }
    }
    renderTime();
    frameRequest = requestAnimationFrame(playStep);
  }

  playButton.onclick = () => {
    if (!info) return;
    if (playing) {
      stopPlaying();
      return;
    }
    const now = video.currentTime;
    if (!parts.some((p) => now >= p.start && now < p.end)) {
      video.currentTime = (parts.find((p) => p.start > now) ?? parts[0]).start;
    }
    playing = true;
    playButton.textContent = "Pause";
    video.play().catch(() => stopPlaying());
    frameRequest = requestAnimationFrame(playStep);
  };

  video.addEventListener("seeked", renderTime);
  video.addEventListener("ended", stopPlaying);
  video.addEventListener("error", () => {
    if (video.getAttribute("src")) showError("The browser could not play this video.");
  });

  function readSavedParts() {
    let saved = [];
    try {
      saved = JSON.parse(partsWidget.value || "[]");
    } catch {
      saved = [];
    }
    const valid = (Array.isArray(saved) ? saved : [])
      .map((p) => ({ start: clampTime(snap(Number(p.start))), end: clampTime(snap(Number(p.end))) }))
      .filter((p) => p.end > p.start)
      .sort((a, b) => a.start - b.start);
    return valid.length ? valid : [{ start: 0, end: duration() }];
  }

  async function loadFile(name, keepParts) {
    const token = ++loadToken;
    stopPlaying();
    info = null;
    render();
    if (!name) {
      video.removeAttribute("src");
      summary.textContent = "Choose a video";
      return;
    }
    summary.classList.remove("rc-error");
    summary.textContent = "Loading...";
    const query = encodeURIComponent(name);
    try {
      const response = await api.fetchApi(`/roughcut/info?file=${query}`);
      const result = await response.json();
      if (token !== loadToken) return;
      if (!response.ok) {
        showError(result.error ?? "Could not read this video.");
        return;
      }
      info = result;
    } catch {
      if (token === loadToken) showError("Could not read this video.");
      return;
    }
    parts = keepParts ? readSavedParts() : [{ start: 0, end: duration() }];
    selected = 0;
    video.src = api.apiURL(`/roughcut/media?file=${query}`);
    video.currentTime = parts[0].start;
    changed();
  }

  const originalCallback = fileWidget.callback;
  fileWidget.callback = function (value, ...rest) {
    const result = originalCallback?.apply(this, [value, ...rest]);
    if (value !== node.rcLoadedFile) {
      node.rcLoadedFile = value;
      loadFile(value, false);
    }
    return result;
  };

  let configured = false;
  const originalConfigure = node.onConfigure;
  node.onConfigure = function (...args) {
    const result = originalConfigure?.apply(this, args);
    configured = true;
    node.rcLoadedFile = fileWidget.value;
    loadFile(fileWidget.value, true);
    return result;
  };

  const originalRemoved = node.onRemoved;
  node.onRemoved = function (...args) {
    stopPlaying();
    video.removeAttribute("src");
    return originalRemoved?.apply(this, args);
  };

  setTimeout(() => {
    if (!configured) {
      node.rcLoadedFile = fileWidget.value;
      loadFile(fileWidget.value, true);
    }
  }, 0);
}

app.registerExtension({
  name: "RoughCut.Timeline",
  nodeCreated(node) {
    if (node.comfyClass === NODE_ID) attachTimeline(node);
  },
});
