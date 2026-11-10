# RoughCut for ComfyUI

Small nodes for rough video editing inside a workflow: pick the parts of a video you want on a timeline, cut, join, change speed, swap audio, and convert between video and images.

It isn't a video editor. Each node does one simple job as a video passes through your workflow.

## Install

Requires ComfyUI 0.44 or newer. There are no extra Python dependencies.

Tested on ComfyUI 0.44.2 with generated test clips. Real camera footage, including rotated phone videos and HEVC, hasn't been tested yet.

```
cd ComfyUI/custom_nodes
git clone https://github.com/ArDRaFi/ComfyUI-RoughCut
```

Then restart ComfyUI.

## Nodes

| Node | What it does |
|---|---|
| **RC Load Video** | Load a video and choose which parts to pass on, on a timeline |
| **RC Images to Video** | IMAGE batch to VIDEO, by frame rate, target length, or to fit an audio clip |
| **RC Video to Images** | Decode only a range to IMAGE, with every Nth frame, a frame limit and resizing |
| **RC Grab Frame** | Take the first, last or any one frame, handy for chaining image-to-video |
| **RC Cut Video** | Split a video into two clips at a point in time |
| **RC Join Videos** | Join clips, even of different size or frame rate, with an optional crossfade |
| **RC Speed / Reverse** | Speed up, slow down or reverse, keeping audio in sync and at its pitch |
| **RC Video Audio** | Keep, replace or mute a video's sound, and output it as AUDIO |
| **RC Video Info** | Width, height, frame rate, frames, seconds and whether it has sound |
| **RC Preview Video** | See any VIDEO on the node without saving a file |

## Picking parts of a video

RC Load Video starts with one part covering the whole video, so you can use it as it is.

- Drag the ends of the blue bar to choose a range, or drag the bar to move it.
- **+ Add part** adds another range. With no free space it splits the selected part at the playhead.
- **Delete part** removes the selected part. **Set start** and **Set end** use the playhead position.
- **Play parts** plays only what is selected.
- Upload with the button, or drop a video on the node. Changing the video resets the selection.

Parts are joined in time order and are exact to the frame. The IMAGE and AUDIO outputs are only decoded when connected, so a long video costs nothing until you need its frames.

## Good to know

- Cutting, trimming, and replacing audio don't re-encode the picture where possible. Join with mismatched clips or a crossfade, and Speed / Reverse, re-encode to 8-bit H.264.
- Long edits stream through a temporary file instead of loading into memory. If decoding to IMAGE wouldn't fit in free RAM, the node stops and suggests every Nth frame, a frame limit, or resizing.
- Formats browsers can't play, such as MKV, are previewed through a small temporary copy. Your original file is what gets used.
- Temporary files go in ComfyUI's temp folder, which ComfyUI clears when it starts.

ComfyUI also has its own Crop Video, Trim Video and Concatenate Video nodes, and these work alongside this pack.

## Example workflows

See [example_workflows](example_workflows). Load your own video and audio into the input nodes before running them.

## Development

Unit tests, from this folder:

```
python -m unittest discover tests
```

`tests/e2e.py` runs real ComfyUI workflows on synthetic clips whose frames carry their own index, and checks exactly which frames come out.

## License

GPL-3.0. This is an independent project, not affiliated with Comfy Org.
